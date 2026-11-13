"""Task 6a: WS connect / auth / heartbeat / resume / tenant isolation / supersede."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from interviewer import database as db
from interviewer import events
from interviewer.main import create_app
from interviewer.realtime.session_store import CLOSE_SUPERSEDED
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
            assert json.loads(ws.receive_text())["type"] == "avatar_ready"
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
    """Invite token for interview A cannot open interview B (session_id isolation).

    WS auth binds tenant from the interview row after token match; a foreign
    interview id never accepts another interview's invite token.
    """
    with _app_client(tmp_path) as client:
        interview_a, token_a = _seed_invited_interview(client)
        interview_b, token_b = _seed_invited_interview(client)
        service = client.app.state.service
        with service.database.unit_of_work() as connection:
            row_a = db.one(connection, db.interviews, interview_a)
            row_b = db.one(connection, db.interviews, interview_b)
            assert row_a is not None and row_b is not None
            assert str(row_a["tenant_id"]) == DEFAULT_TENANT_ID
            assert str(row_b["tenant_id"]) == DEFAULT_TENANT_ID
            assert interview_a != interview_b
            assert token_a != token_b

        with client.websocket_connect(f"/ws/interview/{interview_b}") as ws:
            ws.send_text(json.dumps({
                "v": "aii-ws-v1", "type": "auth", "token": token_a,
            }))
            err = json.loads(ws.receive_text())
            assert err["type"] == "error"
            assert err["code"] == "UNAUTHORIZED"
            assert client.app.state.session_store.get(interview_b) is None


def test_ws_second_connection_supersedes(tmp_path: Path) -> None:
    """D74: second authenticated writer immediately closes the first with 4000."""
    with _app_client(tmp_path) as client:
        interview_id, token = _seed_invited_interview(client)
        auth = json.dumps({"v": "aii-ws-v1", "type": "auth", "token": token, "resumeFromSeq": 0})
        with client.websocket_connect(f"/ws/interview/{interview_id}") as ws1:
            ws1.send_text(auth)
            assert json.loads(ws1.receive_text())["type"] == "ready"
            assert json.loads(ws1.receive_text())["type"] == "avatar_ready"
            first_conn = client.app.state.session_store.get(interview_id)
            assert first_conn is not None
            first_id = first_conn.connection_id

            with client.websocket_connect(f"/ws/interview/{interview_id}") as ws2:
                ws2.send_text(auth)
                assert json.loads(ws2.receive_text())["type"] == "ready"
                assert json.loads(ws2.receive_text())["type"] == "avatar_ready"
                second = client.app.state.session_store.get(interview_id)
                assert second is not None
                assert second.connection_id != first_id

                with pytest.raises(WebSocketDisconnect) as closed:
                    ws1.receive_text()
                assert closed.value.code == CLOSE_SUPERSEDED

                ws2.send_text(json.dumps({"v": "aii-ws-v1", "type": "ping", "t": 7}))
                assert json.loads(ws2.receive_text()) == {
                    "v": "aii-ws-v1", "type": "pong", "t": 7,
                }


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
