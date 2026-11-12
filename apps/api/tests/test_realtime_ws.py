"""Task 6a: WS connect / auth / heartbeat / resume / tenant isolation."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from interviewer import events
from interviewer.main import create_app
from interviewer.settings import Settings
from interviewer.tenancy import DEFAULT_TENANT_ID


def _app_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        sqlite_path=str(tmp_path / "ws.sqlite3"),
        secret="fixture-" * 8,
        admin_key="fixture-admin",
        recruiter_key="fixture-recruiter",
    )
    return TestClient(create_app(settings))


def _seed_invited_interview(client: TestClient) -> tuple[str, str]:
    assert client.post("/api/auth/login", json={}).status_code == 200
    job = client.post(
        "/api/jobs",
        json={
            "title": "WS岗位" + uuid4().hex[:4],
            "jdText": "面向研发的岗位说明，负责实验系统实现、质量验证、协作与学习，以量化结果和个人贡献说明任务成效。",
            "recruitmentTrack": "general",
        },
    )
    assert job.status_code == 201, job.text
    job_id = job.json()["id"]
    extracted = client.post(f"/api/jobs/{job_id}/competencies:extract", json={})
    assert extracted.status_code == 200, extracted.text
    assert client.patch(
        f"/api/jobs/{job_id}/competencies",
        json={"competencies": extracted.json()["competencies"]},
    ).status_code == 200
    person = client.post("/api/candidates", json={"jobId": job_id, "fullName": "WS候选人"})
    assert person.status_code == 201, person.text
    assert client.post(
        f"/api/candidates/{person.json()['id']}/resume",
        json={"text": "技能Python；项目：我主导实验模块，个人负责实现和验证，将处理耗时降低30%。"},
    ).status_code == 201
    invited = client.post(
        "/api/interviews",
        json={
            "jobId": job_id,
            "candidateId": person.json()["id"],
            "durationMinutes": 15,
            "mode": "text",
            "cameraRequired": False,
        },
    )
    assert invited.status_code == 201, invited.text
    body = invited.json()
    return str(body["interviewId"]), str(body["inviteToken"])


def test_ws_auth_ping_and_resume(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        interview_id, token = _seed_invited_interview(client)
        service = client.app.state.service
        with service.database.unit_of_work() as connection:
            events.append_event(connection, interview_id, "state_changed", {"from": "invited", "to": "invited"})
            events.append_event(connection, interview_id, "question_asked", {"seq": 1})

        with client.websocket_connect(f"/ws/interview/{interview_id}") as ws:
            ws.send_text(json.dumps({
                "v": "aii-ws-v1", "type": "auth", "token": token, "resumeFromSeq": 0,
            }))
            ready = json.loads(ws.receive_text())
            assert ready["type"] == "ready"
            assert ready["interviewId"] == interview_id
            assert ready["resumeFromSeq"] >= 2
            replay = json.loads(ws.receive_text())
            assert replay["type"] == "event_replay"
            assert len(replay["events"]) >= 2
            ws.send_text(json.dumps({"v": "aii-ws-v1", "type": "ping", "t": 42}))
            pong = json.loads(ws.receive_text())
            assert pong["type"] == "pong" and pong["t"] == 42


def test_ws_rejects_bad_token(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        interview_id, _token = _seed_invited_interview(client)
        with client.websocket_connect(f"/ws/interview/{interview_id}") as ws:
            ws.send_text(json.dumps({
                "v": "aii-ws-v1", "type": "auth", "token": "not-the-invite-token",
            }))
            err = json.loads(ws.receive_text())
            assert err["type"] == "error"
            assert err["code"] == "UNAUTHORIZED"


def test_ws_cross_tenant_invite_rejected(tmp_path: Path) -> None:
    """Token for interview A cannot open a different interview B session id."""
    with _app_client(tmp_path) as client:
        _interview_a, token_a = _seed_invited_interview(client)
        interview_b, _token_b = _seed_invited_interview(client)
        with client.websocket_connect(f"/ws/interview/{interview_b}") as ws:
            ws.send_text(json.dumps({
                "v": "aii-ws-v1", "type": "auth", "token": token_a,
            }))
            err = json.loads(ws.receive_text())
            assert err["type"] == "error"
            assert err["code"] == "UNAUTHORIZED"


def test_session_store_replay_filters_by_seq(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        interview_id, _token = _seed_invited_interview(client)
        service = client.app.state.service
        store = client.app.state.session_store
        with service.database.unit_of_work() as connection:
            events.append_event(connection, interview_id, "consent_granted", {})
            events.append_event(connection, interview_id, "state_changed", {"to": "interviewing"})
        after = store.events_after(service, interview_id, DEFAULT_TENANT_ID, after_seq=1)
        assert all(int(str(row["seq"])) > 1 for row in after)
        assert store.latest_seq(service, interview_id, DEFAULT_TENANT_ID) >= 2
