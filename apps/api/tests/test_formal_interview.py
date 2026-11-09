from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from conftest import STRONG, begin
from interviewer.contracts import Object, ReportDocument, json_object
from interviewer.service import Service

ADMIN = {"Authorization": "Bearer fixture-admin"}
BASE = "/api/formal-interviews"
RECORDS = "/api/admin/interviews"
FIXED = [
    ("introduction", "研究方向"), ("cet4", "425分"), ("project", "个人贡献"),
    ("graduate_courses", "不及格记录"), ("motivation", "为什么选择本岗位"),
    ("compensation", "期望月薪、期望年薪及可接受最低薪资"),
    ("career", "未来1至3年"), ("self_evaluation", "一项优势和一项待提升能力"),
    ("work_arrangements", "到岗时间、工作地点或出差安排"),
]
INPUT: Object = {
    "title": "数据平台工程师",
    "candidateName": "合成候选人",
    "jdText": "负责维护离线数据管道和数据质量告警，并和业务团队一起制定服务可靠性指标。",
    "resumeText": "简历项目：重构库存同步服务，降低超时比例，并为同步任务补充监控与回滚机制。\n邮箱：fixture@example.com",
}


def test_text_interview_report_and_admin_records(client: TestClient) -> None:
    assert client.post("/api/auth/login", json={}).status_code == 200
    assert client.get(RECORDS).status_code in {401, 403}
    key = {"Idempotency-Key": str(uuid4())}
    created = client.post(BASE, json=INPUT, headers=key)
    assert created.status_code == 201, created.text
    assert client.post(BASE, json=INPUT, headers=key).json() == created.json()
    assert client.post(BASE, json={**INPUT, "title": "另一岗位"}, headers=key).status_code == 409
    invitation = json_object(created.json())
    assert invitation["questionCount"] == 12
    identity = str(invitation["interviewId"])
    candidate = f"/api/interviews/{identity}"
    record = f"{RECORDS}/{identity}"
    listing = client.get(RECORDS, headers=ADMIN).json()["items"]
    assert [(row["id"], row["status"]) for row in listing] == [(identity, "invited")]
    assert client.get(record, headers=ADMIN).json()["turns"] == []
    token = {"Authorization": f"Bearer {invitation['inviteToken']}"}
    denied = client.post(candidate + "/turns", headers=token, json={"action": "answer", "content": STRONG})
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "CONSENT_REQUIRED"
    headers = begin(client, invitation)
    questions = [*FIXED, (None, "离线数据管道"), (None, "重构库存同步服务"), (None, "离线数据管道")]
    for seq, (topic, expected) in enumerate(questions, 1):
        state = client.get(candidate + "/state", headers=headers).json()
        assert state["mode"] == "text" and state["cameraRequired"] is False
        assert state["questionSeq"] == seq and expected in state["currentQuestion"]["text"]
        assert state["currentQuestion"]["topicKey"] == topic
        if topic in {"cet4", "graduate_courses"}:
            assert state["currentQuestion"]["assessmentMode"] == "eligibility"
            assert state["currentQuestion"]["mandatory"] is True
            assert client.post(candidate + "/turns", headers=headers, json={"action": "skip"}).status_code == 400
        assert state["followupsAsked"] == 0
        answer = {"action": "answer", "content": STRONG + "\n邮箱：fixture@example.com", "expectedQuestionSeq": seq}
        turn_headers = {**headers, "Idempotency-Key": str(uuid4())}
        result = client.post(candidate + "/turns", headers=turn_headers, json=answer)
        assert result.status_code == 200, result.text
        if seq < len(questions):
            stale = client.post(candidate + "/turns", headers=headers, json=answer)
            assert stale.status_code == 409, stale.text
            assert client.get(record, headers=ADMIN).json()["interview"]["status"] == "interviewing"

    replayed = client.post(candidate + "/turns", headers=turn_headers, json=answer)
    assert replayed.status_code == 200 and '"replayed":true' in replayed.text
    assert replayed.text.split("event: done")[-1] == result.text.split("event: done")[-1]
    assert client.get(candidate + "/state", headers=headers).json()["status"] == "scoring"
    assert client.post(record + "/score", json={}).status_code in {401, 403}
    scored = client.post(record + "/score", headers=ADMIN, json={})
    assert scored.status_code == 200, scored.text
    report = ReportDocument.model_validate(scored.json())
    assert {item.seq for item in report.questions} == {3, 5, 7, 8, 10, 11, 12}
    assert report.coverage == 1 and report.evidence and report.recommendation == "mixed"
    assert report.campus and report.campus["status"] == "pending"
    assert all(row.quote in STRONG for row in report.evidence)
    detail = client.get(record, headers=ADMIN)
    assert detail.status_code == 200, detail.text
    assert detail.json()["report"]["reportId"] == report.report_id
    assert "fixture@example.com" not in detail.text and invitation["inviteToken"] not in detail.text
    client.cookies.delete("aii_recruiter")
    assert client.post("/api/admin/login", json={}).status_code == 200
    for revision, (score, failed) in enumerate([(424, 0), (425, 1), (425, 0)], report.revision):
        verified = client.patch(candidate + "/eligibility", json={
            "expectedRevision": revision, "cet4Score": score, "failedGraduateCourses": failed,
            "cet4Reference": "合成四级成绩报告", "transcriptReference": "合成完整研究生成绩单", "note": "测试人工核验硬性资格",
        })
        assert verified.status_code == 200, verified.text
        result_report = verified.json()
        met = score == 425 and failed == 0
        assert result_report["campus"]["status"] == ("met" if met else "not_met")
        assert result_report["recommendation"] == ("strong_yes" if met else "no")
        assert result_report["overallScore"] == report.overall_score
    assert client.post(candidate + "/withdraw", headers=headers, json={}).status_code == 200
    withdrawn = client.get(record, headers=ADMIN).json()
    assert withdrawn["interview"]["status"] == "cancelled"
    assert withdrawn["turns"] == [] and withdrawn["report"] is None


def test_formal_interview_rejects_client_supplied_fixed_questions(client: TestClient) -> None:
    assert client.post("/api/auth/login", json={}).status_code == 200
    response = client.post(BASE, json={**INPUT, "fixedQuestions": ["请说明你的婚育情况"]})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert client.get("/api/jobs").json()["jobs"] == []


def test_formal_deadline_still_requires_qualification_questions(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.post("/api/auth/login", json={}).status_code == 200
    invitation = json_object(client.post(BASE, json=INPUT).json())
    headers = begin(client, invitation)
    candidate = f"/api/interviews/{invitation['interviewId']}"
    monkeypatch.setattr(Service, "remaining", lambda _service, _row: 0)
    assert client.post(candidate + "/turns", headers=headers, json={"action": "skip"}).status_code == 200
    for topic in ("cet4", "graduate_courses"):
        state = client.get(candidate + "/state", headers=headers).json()
        assert state["currentQuestion"]["topicKey"] == topic
        assert client.post(candidate + "/turns", headers=headers, json={"action": "answer", "content": "待核验"}).status_code == 200
    assert client.get(candidate + "/state", headers=headers).json()["status"] == "scoring"


def test_admin_records_include_earlier_invitations(client: TestClient) -> None:
    assert client.post("/api/auth/login", json={}).status_code == 200
    identities = set()
    for index in range(26):
        invited = client.post(BASE, json={**INPUT, "candidateName": f"合成候选人 {index}"})
        assert invited.status_code == 201, invited.text
        identities.add(invited.json()["interviewId"])
    first = client.get(RECORDS, headers=ADMIN).json()
    assert len(first["items"]) == 25 and first["nextCursor"]
    second = client.get(RECORDS, headers=ADMIN, params={"before": first["nextCursor"]}).json()
    assert len(second["items"]) == 1 and second["nextCursor"] is None
    assert {row["id"] for row in first["items"] + second["items"]} == identities
