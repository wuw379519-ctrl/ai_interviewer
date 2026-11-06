from uuid import uuid4

from fastapi.testclient import TestClient

from conftest import STRONG, begin
from interviewer.contracts import Object, ReportDocument, json_object

ADMIN = {"Authorization": "Bearer fixture-admin"}
BASE = "/api/formal-interviews"
RECORDS = "/api/admin/interviews"
FIXED = ["请介绍一次你主导交付的经历？", "你是如何处理项目里的分歧的？"]
INPUT: Object = {
    "title": "数据平台工程师",
    "candidateName": "合成候选人",
    "jdText": "负责维护离线数据管道和数据质量告警，并和业务团队一起制定服务可靠性指标。",
    "resumeText": "简历项目：重构库存同步服务，降低超时比例，并为同步任务补充监控与回滚机制。\n邮箱：fixture@example.com",
    "fixedQuestions": FIXED,
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
    assert invitation["questionCount"] == 5
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
    for seq, expected in enumerate([*FIXED, "离线数据管道", "重构库存同步服务", "离线数据管道"], 1):
        state = client.get(candidate + "/state", headers=headers).json()
        assert state["mode"] == "text" and state["cameraRequired"] is False
        assert state["questionSeq"] == seq and expected in state["currentQuestion"]["text"]
        assert state["followupsAsked"] == 0
        answer = {"action": "answer", "content": STRONG + "\n邮箱：fixture@example.com", "expectedQuestionSeq": seq}
        turn_headers = {**headers, "Idempotency-Key": str(uuid4())}
        result = client.post(candidate + "/turns", headers=turn_headers, json=answer)
        assert result.status_code == 200, result.text
        if seq < 5:
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
    assert len(report.questions) == 5 and report.coverage == 1 and report.evidence
    assert all(row.quote in STRONG for row in report.evidence)
    detail = client.get(record, headers=ADMIN)
    assert detail.status_code == 200, detail.text
    assert detail.json()["report"]["reportId"] == report.report_id
    assert "fixture@example.com" not in detail.text and invitation["inviteToken"] not in detail.text
    assert client.post(candidate + "/withdraw", headers=headers, json={}).status_code == 200
    withdrawn = client.get(record, headers=ADMIN).json()
    assert withdrawn["interview"]["status"] == "cancelled"
    assert withdrawn["turns"] == [] and withdrawn["report"] is None


def test_formal_interview_rejects_unsuitable_fixed_questions(client: TestClient) -> None:
    assert client.post("/api/auth/login", json={}).status_code == 200
    response = client.post(BASE, json={**INPUT, "fixedQuestions": ["请说明你的婚育情况"]})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert client.get("/api/jobs").json()["jobs"] == []


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
