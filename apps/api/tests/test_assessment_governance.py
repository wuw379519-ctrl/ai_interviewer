from datetime import timedelta
from typing import cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from interviewer import database as db
from interviewer.contracts import AssessmentSample, Contract, Object, ReportDocument, json_object
from interviewer.provider import Generation
from interviewer.service import Service
from conftest import STRONG, begin, invitation


def completed(client: TestClient, track: str = "general") -> str:
    created, _ = invitation(client, track)
    identity, headers = str(created["interviewId"]), begin(client, created)
    for _ in range(int(str(created["questionCount"]))):
        assert client.post(f"/api/interviews/{identity}/turns", headers=headers, json={"action": "answer", "content": STRONG}).status_code == 200
    assert client.post(f"/api/interviews/{identity}/finish", headers=headers, json={}).status_code == 200
    return identity


def test_invented_citations_never_produce_scores(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    identity = completed(client)
    service = cast(Service, client.app.state.service)

    def fabricated(_operation: str, _messages: list[dict[str, str]], _schema: type[Contract], fixture: Object) -> Generation[AssessmentSample]:
        sample = AssessmentSample.model_validate(fixture)
        for row in sample.questions:
            row.evidence[0].quote = "没有出现在候选人原始发言中的内容"
        return Generation(sample, service.provider.usage(10, 10))
    monkeypatch.setattr(service.provider, "structured", fabricated)
    response = client.post(f"/api/interviews/{identity}/score", json={})
    assert response.status_code == 200, response.text
    report = ReportDocument.model_validate(response.json())
    assert all(row.score == "insufficient_evidence" for row in report.dimensions)
    assert not report.evidence and report.overall_score is None and report.recommendation == "mixed"


def test_sampling_difference_and_human_revision_audit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    identity = completed(client)
    service = cast(Service, client.app.state.service)
    count = 0

    def variable(_operation: str, _messages: list[dict[str, str]], _schema: type[Contract], fixture: Object) -> Generation[AssessmentSample]:
        nonlocal count
        count += 1
        sample = AssessmentSample.model_validate(fixture)
        if count == 2:
            for row in sample.questions:
                row.score = "2"
        return Generation(sample, service.provider.usage(10, 10))
    monkeypatch.setattr(service.provider, "structured", variable)
    report = ReportDocument.model_validate(client.post(f"/api/interviews/{identity}/score", json={}).json())
    assert all(row.needs_review and row.score == "2" for row in report.dimensions)
    assert all(row.sample_values == ["5", "2"] for row in report.dimensions)
    dimension = report.dimensions[0]
    revised = client.patch(f"/api/scores/{dimension.score_id}", json={"value": "3", "expectedRevision": report.revision,
                           "evidenceId": dimension.evidence_ids[0], "reason": "人工核验原文后调整为三级行为"})
    assert revised.status_code == 200, revised.text
    latest = ReportDocument.model_validate(revised.json())
    assert latest.revisions[0].old_value == "2" and latest.revisions[0].new_value == "3"
    assert latest.revisions[0].actor_id == "recruiter"
    assert client.post(f"/api/interviews/{identity}/score", json={"rerun": True}).status_code == 409


@pytest.mark.parametrize("score,failed,status", [(425, 0, "met"), (424, 0, "not_met"), (425, 1, "not_met"), (None, None, "pending")])
def test_eligibility_never_automatically_rejects(client: TestClient, score: int | None, failed: int | None, status: str) -> None:
    identity = completed(client, "graduate_campus")
    report = ReportDocument.model_validate(client.post(f"/api/interviews/{identity}/score", json={}).json())
    response = client.patch(f"/api/interviews/{identity}/eligibility", json={"expectedRevision": report.revision,
                            "cet4Score": score, "cet4Reference": "已核对合成四级来源" if score is not None else "",
                            "failedGraduateCourses": failed, "transcriptReference": "已核对完整合成成绩单" if failed is not None else "", "note": "岗位资格只由招聘者查看证明核验"})
    assert response.status_code == 200, response.text
    amended = ReportDocument.model_validate(response.json())
    assert amended.campus and amended.campus["status"] == status
    assert amended.status == "report_ready"
    assert amended.recommendation == ("strong_yes" if status == "met" else "mixed")
    review = client.post(f"/api/interviews/{identity}/review", json={"expectedRevision": amended.revision, "note": "招聘者已复核资格事实与原话证据"})
    assert review.status_code == (409 if status == "pending" else 200)


def test_erasure_rolls_back_on_failure(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    created, person = invitation(client)
    service = cast(Service, client.app.state.service)
    headers = begin(client, created)
    client.post("/api/admin/login", json={})
    previous = service.audit

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic transaction failure")
    monkeypatch.setattr(service, "audit", fail)
    body = {"confirmCandidateId": person["id"], "reason": "合成事务回滚验证"}
    assert client.request("DELETE", f"/api/candidates/{person['id']}", json=body).status_code == 500
    monkeypatch.setattr(service, "audit", previous)
    assert client.get(f"/api/interviews/{created['interviewId']}/state", headers=headers).status_code == 200
    assert client.request("DELETE", f"/api/candidates/{person['id']}", json=body).status_code == 200


def test_policy_deadlines_signed_previews_and_replay(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    created, person = invitation(client)
    client.post("/api/admin/login", json={})
    key = str(uuid4())
    body = {"retentionDays": 30, "expectedRevision": 1, "reason": "缩短新资料的保留期"}
    assert client.patch("/api/admin/retention", headers={"Idempotency-Key": key}, json=body).status_code == 200
    assert client.patch("/api/admin/retention", json={"retentionDays": 60, "expectedRevision": 2, "reason": "调整新资料的保留期限"}).status_code == 200
    assert json_object(client.patch("/api/admin/retention", headers={"Idempotency-Key": key}, json=body).json())["retentionDays"] == 60
    service = cast(Service, client.app.state.service)
    with service.database.transaction() as connection:
        original = db.one(connection, db.interviews, str(created["interviewId"]))
        assert original and original["retention_days"] == 90
        db.update(connection, db.candidates, str(person["id"]), retained_until=db.now() - timedelta(seconds=1))
    preview = json_object(json_object(client.get("/api/admin/retention").json())["preview"])
    assert person["id"] in cast(list[str], preview["candidateIds"])
    execution = {"previewToken": preview["previewToken"], "reason": "合成到期批次清理验证"}
    execution_key = str(uuid4())
    response = client.post("/api/admin/retention/run", headers={"Idempotency-Key": execution_key}, json=execution)
    assert response.status_code == 200 and json_object(response.json())["candidatesErased"] == 1
    import time
    then = time.time()
    monkeypatch.setattr(time, "time", lambda: then + 600)
    assert client.post("/api/admin/retention/run", headers={"Idempotency-Key": execution_key}, json=execution).status_code == 200
    assert client.post("/api/admin/retention/run", json=execution).status_code == 409


def test_database_enforces_citation_scope_and_immutable_source(client: TestClient) -> None:
    identity = completed(client)
    report = ReportDocument.model_validate(client.post(f"/api/interviews/{identity}/score", json={}).json())
    service = cast(Service, client.app.state.service)
    for reference in [None, report.dimensions[1].evidence_ids[0]]:
        with pytest.raises(IntegrityError), service.database.transaction() as connection:
            db.insert(connection, db.scores, {"interview_id": identity, "competency_id": report.dimensions[0].competency_id,
                                            "value": "5", "numeric_value": 5, "attempt": 2, "evidence_id": reference})
    with pytest.raises(IntegrityError), service.database.transaction() as connection:
        db.update(connection, db.turns, report.evidence[0].turn_id, content="修改已经引用的原话")
