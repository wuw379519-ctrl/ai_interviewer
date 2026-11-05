import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from interviewer import database as db
from interviewer.contracts import CompetencySet, Contract, Object, PlanDraft
from interviewer.domain import TOPICS, TRANSITIONS, build_plan, fixture_competencies, transition
from interviewer.errors import DomainError
from interviewer.evals import run_evals
from interviewer.provider import Generation
from interviewer.safety import INJECTION, PROTECTED, assessment_text, load_resource, redact, sanitize_metadata, sanitize_profile
from conftest import STRONG, begin, invitation


@pytest.mark.parametrize("minutes", [15, 30, 45])
@pytest.mark.parametrize("count", [4, 5, 6])
@pytest.mark.parametrize("graduate", [False, True])
def test_plan_dimensions_budgets_and_safe_questions(minutes: int, count: int, graduate: bool) -> None:
    base = fixture_competencies(graduate).competencies[0].payload()
    weights = [2500] * 4 if count == 4 else [2000] * 5 if count == 5 else [1665, 1667, 1667, 1667, 1667, 1667]
    dimensions = [{**base, "id": str(uuid4()), "name": f"维度{index}", "weight": weight / 10000} for index, weight in enumerate(weights)]
    plan, version = build_plan(dimensions, minutes, graduate)
    assert len(plan) >= 8 and version
    assert sum(int(str(row["timeBudgetSec"])) for row in plan) == minutes * 60 * 0.95
    assert all(sum(row["competencyId"] == dimension["id"] and row["assessmentMode"] == "scored" for row in plan) >= 2 for dimension in dimensions)
    assert not any(PROTECTED.search(str(row["prompt"])) for row in plan)
    if graduate:
        assert sum(bool(row["mandatory"]) for row in plan) == 9
        assert len(plan) == {4: 13, 5: 15, 6: 17}[count]


@pytest.mark.parametrize("current", list(TRANSITIONS))
def test_state_machine_only_declared_transitions_and_consented_gate(current: str) -> None:
    for target in TRANSITIONS:
        if target == "consented":
            with pytest.raises(DomainError):
                transition(current, target)
        if target == current or target in TRANSITIONS[current]:
            transition(current, target, True)
        else:
            with pytest.raises(DomainError):
                transition(current, target, True)


def test_resume_whitelist_nested_attributes_and_contact_redaction() -> None:
    profile = sanitize_profile({"age": 32, "gender": "女", "school": "某大学", "phone": "13800138000",
                                "summary": "姓名：合成候选人，性别：女，年龄：32，院校：示例大学。技能Python。",
                                "experiences": [{"company": "研究团队", "title": "研究助理", "start": None, "end": None,
                                                 "gender": "女", "highlights": ["联系13800138000，邮箱 fixture@example.com"]}],
                                "skills": ["Python"], "projects": [{"name": "实验项目", "detail": "我负责分析", "age": 32}]}, "合成候选人")
    raw = profile.model_dump_json()
    for secret in ["合成候选人", "13800138000", "fixture@example.com", '"gender"', '"age"', "示例大学", "性别：女"]:
        assert secret not in raw
    assert profile.skills == ["Python"]
    metadata = sanitize_metadata({"phone": 13800138000, "nested": {"email": "fixture@example.com"}, "apiKey": "fixture-key"})
    assert "13800138000" not in json.dumps(metadata) and "fixture-key" not in json.dumps(metadata)


@pytest.mark.parametrize("attack", load_resource("evals.json")["attacks"])
def test_attacks_are_untrusted_data_not_scoring_instructions(attack: str) -> None:
    assert INJECTION.search(attack)
    assert assessment_text(attack + "\n" + STRONG).strip() == STRONG


def test_all_twenty_four_eval_transcripts_and_evidence() -> None:
    summary = run_evals()
    assert summary["transcripts"] == 24 and summary["injectionResisted"] == 10
    assert summary["evidenceCitationRate"] == 1 and summary["protectedQuestions"] == 0


def test_weights_and_protected_competencies_rejected(client: TestClient) -> None:
    with pytest.raises(ValidationError):
        CompetencySet.model_validate({"competencies": [{**row.payload(), "weight": 0.2} for row in fixture_competencies(False).competencies]})
    created, _ = invitation(client)
    assert client.patch("/api/admin/retention", json={"retentionDays": 0, "expectedRevision": 1, "reason": "无效策略"}).status_code == 403
    headers = {"Authorization": "Bearer " + str(created["inviteToken"])}
    response = client.post(f"/api/interviews/{created['interviewId']}/consent", headers=headers, json={"accepted": True, "consentVersion": "obsolete"})
    assert response.status_code == 400
    assert client.post("/api/auth/login", headers={"Origin": "https://attacker.example"}, json={}).status_code == 401


@pytest.mark.parametrize("revoked", [False, True])
def test_preconsent_admission_never_reads_request_content(client: TestClient, revoked: bool) -> None:
    created, _ = invitation(client)
    if revoked:
        begin(client, created)
        service = client.app.state.service
        with service.database.transaction() as connection:
            record = db.rows(connection, select(db.consents).where(db.consents.c.interview_id == created["interviewId"]))[0]
            db.update(connection, db.consents, str(record["id"]), revoked_at=db.now())
    reads = 0
    messages: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        nonlocal reads
        reads += 1
        return {"type": "http.request", "body": b"malformed sensitive content", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
             "scheme": "http", "path": f"/api/interviews/{created['interviewId']}/turns", "raw_path": b"/api/interviews/fixture/turns",
             "query_string": b"", "root_path": "", "headers": [(b"authorization", ("Bearer " + str(created["inviteToken"])).encode()), (b"content-type", b"application/json")],
             "server": ("testserver", 80), "client": ("127.0.0.1", 9000)}
    asyncio.run(client.app(scope, receive, send))
    assert reads == 0
    assert messages[0]["status"] == 409
    assert redact("fixture@example.com") != "fixture@example.com"


def test_gateway_cannot_rewrite_fixed_graduate_topics(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    service = client.app.state.service
    monkeypatch.setattr(service.provider, "name", "internal")
    generated_count = 0

    def gateway(operation: str, _messages: list[dict[str, str]], schema: type[Contract], fixture: Object) -> Generation[Contract]:
        nonlocal generated_count
        result = schema.model_validate(fixture)
        if operation == "question_generation":
            assert isinstance(result, PlanDraft)
            generated_count = len(result.questions)
            for row in result.questions:
                row.prompt = "请描述你在岗位相关项目中的个人贡献与验证结果。"
        return Generation(result, service.provider.usage(10, 10))
    monkeypatch.setattr(service.provider, "structured", gateway)
    created, _ = invitation(client, "graduate_campus")
    assert generated_count == 0 and created["questionCount"] == 13
    with service.database.transaction() as connection:
        questions = service.question_rows(connection, str(created["interviewId"]))
        assert len(questions) == 13
        for topic in TOPICS:
            assert next(row["prompt"] for row in questions if row["topic_key"] == topic["key"]) == topic["prompt"]
