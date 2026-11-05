import json
from uuid import uuid4

from fastapi.testclient import TestClient

from interviewer.contracts import ReportDocument, json_object
from conftest import STRONG, begin, invitation


def test_full_graduate_interview_evidence_and_human_review(client: TestClient) -> None:
    created, _person = invitation(client, "graduate_campus")
    assert created["questionCount"] == 13
    identity = str(created["interviewId"])
    headers = begin(client, created)
    for _ in range(13):
        response = client.post(f"/api/interviews/{identity}/turns", headers={**headers, "Idempotency-Key": str(uuid4())},
                               json={"action": "answer", "content": STRONG})
        assert response.status_code == 200, response.text
        done = next(event for event in response.text.split("\n\n") if event.startswith("event: done\n"))
        assert json_object(json.loads(done.removeprefix("event: done\ndata: ")))["injectionSuspected"] is False
    assert client.post(f"/api/interviews/{identity}/finish", headers=headers, json={}).status_code == 200
    response = client.post(f"/api/interviews/{identity}/score", json={})
    assert response.status_code == 200, response.text
    report = ReportDocument.model_validate(response.json())
    assert len(report.dimensions) == 4 and len(report.questions) == 8
    assert all(row.evidence_ids and row.score == "5" for row in report.dimensions)
    assert report.campus and report.campus["status"] == "pending"
    assert report.recommendation == "mixed" and report.metadata.total_tokens > 0
    assert report.metadata.estimated_cost_usd == 0
    response = client.patch(f"/api/interviews/{identity}/eligibility", json={"expectedRevision": report.revision,
                  "cet4Score": 425, "cet4Reference": "已查看合成四级报告", "failedGraduateCourses": 0,
                  "transcriptReference": "已查看合成研究生完整成绩单", "note": "仅用于合成验收，两项原始材料均已核对"})
    assert response.status_code == 200, response.text
    qualified = ReportDocument.model_validate(response.json())
    assert qualified.campus and qualified.campus["status"] == "met"
    assert qualified.recommendation == "strong_yes"
    response = client.post(f"/api/interviews/{identity}/review", json={"expectedRevision": qualified.revision, "note": "合成测试核对全部证据与资格"})
    assert response.status_code == 200, response.text
    assert ReportDocument.model_validate(response.json()).status == "reviewed"


def test_preconsent_unauthorized_idempotency_and_refresh(client: TestClient) -> None:
    created, _person = invitation(client)
    identity = str(created["interviewId"])
    headers = {"Authorization": "Bearer " + str(created["inviteToken"])}
    assert client.get(f"/api/interviews/{identity}/state").status_code == 401
    response = client.post(f"/api/interviews/{identity}/turns", headers=headers,
                           json={"action": "answer", "content": "不应在同意前采集"})
    assert response.status_code == 409
    state = json_object(client.get(f"/api/interviews/{identity}/state", headers=headers).json())
    assert state["turns"] == []
    headers = begin(client, created)
    key = str(uuid4())
    data = {"action": "answer", "content": "我负责完成了这个模块，效果还不错。"}
    response = client.post(f"/api/interviews/{identity}/turns", headers={**headers, "Idempotency-Key": key}, json=data)
    assert response.status_code == 200 and "ask_followup" in response.text
    response = client.post(f"/api/interviews/{identity}/turns", headers={**headers, "Idempotency-Key": key}, json=data)
    meta = next(event for event in response.text.split("\n\n") if event.startswith("event: meta\n"))
    assert json_object(json.loads(meta.removeprefix("event: meta\ndata: ")))["replayed"] is True
    before = json_object(client.get(f"/api/interviews/{identity}/state", headers=headers).json())
    assert before["followupsAsked"] == 1
    assert client.post(f"/api/interviews/{identity}/pause", headers=headers, json={"paused": True}).status_code == 200
    after = json_object(client.get(f"/api/interviews/{identity}/state", headers=headers).json())
    assert before["currentQuestion"] == after["currentQuestion"]
    assert client.post(f"/api/interviews/{identity}/pause", headers=headers, json={"paused": False}).status_code == 200
    assert client.post(f"/api/interviews/{identity}/withdraw", headers=headers, json={}).status_code == 200
    assert client.get(f"/api/interviews/{identity}/state", headers=headers).status_code == 401


def test_erasure_really_deletes_graph_and_invalidates_cached_invite(client: TestClient) -> None:
    created, person = invitation(client)
    begin(client, created)
    assert client.get("/api/admin/retention").status_code == 403
    assert client.post("/api/admin/login", json={}).status_code == 200
    preview = client.get(f"/api/candidates/{person['id']}")
    assert preview.status_code == 200
    assert json_object(preview.json())["deleted"] is False
    response = client.request("DELETE", f"/api/candidates/{person['id']}", json={"confirmCandidateId": person["id"], "reason": "处理合成资料删除请求"})
    assert response.status_code == 200, response.text
    assert json_object(response.json())["interviewsErased"] == 1
    assert client.get(f"/api/interviews/{created['interviewId']}/state", headers={"Authorization": "Bearer " + str(created["inviteToken"])}).status_code == 401
    remaining = json_object(client.get(f"/api/candidates/{person['id']}").json())
    assert remaining["counts"] == {"interviews": 0, "resumes": 0, "turns": 0, "reports": 0, "scores": 0, "caches": 0}
