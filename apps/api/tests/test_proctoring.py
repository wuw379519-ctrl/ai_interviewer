"""Task 7: proctor_logs, risk rules, WS ingest, tenant isolation."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from interviewer import database as db
from interviewer.main import create_app
from interviewer.proctoring.scorer import (
    ANSWER_LATENCY_FAST_MS,
    TAB_HIDDEN_REVIEW_THRESHOLD,
    score_proctor_risks,
)
from interviewer.proctoring.signals import append_proctor_log, list_proctor_logs
from interviewer.settings import Settings
from interviewer.tenancy import (
    DEFAULT_TENANT_ID,
    reset_current_tenant,
    set_current_tenant,
)


TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_score_tab_switch_positive_and_negative() -> None:
    none = score_proctor_risks([])
    assert none == []
    mild = score_proctor_risks([
        {"signalType": "tab_hidden", "payload": {}},
        {"signalType": "window_blur", "payload": {}},
    ])
    assert any(item.code == "tab_switch_noted" and item.severity == "hint" for item in mild)
    assert all(not item.affects_score for item in mild)
    heavy = [
        {"signalType": "tab_hidden", "payload": {}} for _ in range(TAB_HIDDEN_REVIEW_THRESHOLD)
    ]
    review = score_proctor_risks(heavy)
    assert any(item.code == "excessive_tab_switch" and item.severity == "review" for item in review)


def test_score_answer_latency_positive_and_negative() -> None:
    slow = score_proctor_risks([
        {"signalType": "answer_latency", "payload": {"latencyMs": ANSWER_LATENCY_FAST_MS + 500}},
    ])
    assert not any(item.code == "answer_too_fast" for item in slow)
    fast = score_proctor_risks([
        {"signalType": "answer_latency", "payload": {"latencyMs": 500}},
    ])
    assert any(item.code == "answer_too_fast" and item.severity == "review" for item in fast)
    assert all(item.affects_score is False for item in fast)


def test_score_silence_and_volume_hint_rules() -> None:
    silence = score_proctor_risks([
        {"signalType": "silence_ratio", "payload": {"ratio": 0.85}},
    ])
    assert any(item.code == "high_silence_ratio" and item.severity == "hint" for item in silence)
    quiet_ok = score_proctor_risks([
        {"signalType": "silence_ratio", "payload": {"ratio": 0.2}},
    ])
    assert not any(item.code == "high_silence_ratio" for item in quiet_ok)
    spike = score_proctor_risks([
        {"signalType": "volume_spike", "payload": {"rmsDelta": 5000}},
    ])
    assert any(item.code == "volume_spike" for item in spike)
    no_spike = score_proctor_risks([
        {"signalType": "volume_spike", "payload": {"rmsDelta": 100}},
    ])
    assert not any(item.code == "volume_spike" for item in no_spike)


def _app(tmp_path: Path) -> TestClient:
    settings = Settings(
        sqlite_path=str(tmp_path / "proctor.sqlite3"),
        secret="fixture-" * 8,
        admin_key="fixture-admin",
        recruiter_key="fixture-recruiter",
        provider="fake",
    )
    return TestClient(create_app(settings))


def _seed_interviewing(client: TestClient) -> tuple[str, str]:
    assert client.post("/api/auth/login", json={}).status_code == 200
    job = client.post(
        "/api/jobs",
        json={
            "title": "Proctor" + uuid4().hex[:4],
            "jdText": "面向研发的岗位说明，负责实验系统实现、质量验证、协作与学习，以量化结果和个人贡献说明任务成效。",
            "recruitmentTrack": "general",
        },
    )
    job_id = job.json()["id"]
    extracted = client.post(f"/api/jobs/{job_id}/competencies:extract", json={}).json()
    client.patch(f"/api/jobs/{job_id}/competencies", json={"competencies": extracted["competencies"]})
    person = client.post("/api/candidates", json={"jobId": job_id, "fullName": "Proctor候选人"}).json()
    client.post(
        f"/api/candidates/{person['id']}/resume",
        json={"text": "技能Python；项目：我主导实验模块，个人负责实现和验证，将处理耗时降低30%。"},
    )
    invited = client.post(
        "/api/interviews",
        json={
            "jobId": job_id,
            "candidateId": person["id"],
            "durationMinutes": 15,
            "mode": "text",
            "cameraRequired": False,
        },
    ).json()
    interview_id = str(invited["interviewId"])
    token = str(invited["inviteToken"])
    headers = {"Authorization": f"Bearer {token}"}
    state = client.get(f"/api/interviews/{interview_id}/state", headers=headers).json()
    client.post(
        f"/api/interviews/{interview_id}/consent",
        headers=headers,
        json={"accepted": True, "consentVersion": state["consentVersion"]},
    )
    client.post(f"/api/interviews/{interview_id}/start", headers=headers, json={})
    return interview_id, token


def test_proctor_logs_tenant_isolation(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        interview_id, _token = _seed_interviewing(client)
        service = client.app.state.service
        with service.database.unit_of_work() as connection:
            connection.insert_if_absent(
                db.tenants,
                {"id": TENANT_B, "name": "tenant-b-proctor", "status": "active"},
                ["id"],
            )
        token_a = set_current_tenant(DEFAULT_TENANT_ID)
        try:
            with service.database.unit_of_work() as connection:
                append_proctor_log(connection, interview_id, "tab_hidden", {"hidden": True})
                rows_a = list_proctor_logs(connection, interview_id)
                assert len(rows_a) == 1
                assert rows_a[0]["tenantId"] == DEFAULT_TENANT_ID
        finally:
            reset_current_tenant(token_a)

        token_b = set_current_tenant(TENANT_B)
        try:
            with service.database.unit_of_work() as connection:
                # App-layer list filters by current_tenant — B must not see A's rows.
                rows_b = list_proctor_logs(connection, interview_id)
                assert rows_b == []
        finally:
            reset_current_tenant(token_b)


def test_ws_proctor_signal_persists(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        interview_id, token = _seed_interviewing(client)
        with client.websocket_connect(f"/ws/interview/{interview_id}") as ws:
            ws.send_text(json.dumps({
                "v": "aii-ws-v1", "type": "auth", "token": token, "resumeFromSeq": 0,
            }))
            ready = json.loads(ws.receive_text())
            assert ready["type"] == "ready"
            # Optional event_replay may follow ready.
            ws.send_text(json.dumps({
                "v": "aii-ws-v1",
                "type": "proctor_signal",
                "signalType": "tab_hidden",
                "payload": {"hidden": True},
            }))
            ack = None
            for _ in range(10):
                msg = json.loads(ws.receive_text())
                if msg["type"] == "state_changed" and msg.get("detail", {}).get("signalType") == "tab_hidden":
                    ack = msg
                    break
            assert ack is not None
        service = client.app.state.service
        token_ctx = set_current_tenant(DEFAULT_TENANT_ID)
        try:
            with service.database.unit_of_work() as connection:
                rows = list_proctor_logs(connection, interview_id)
                assert any(row["signalType"] == "tab_hidden" for row in rows)
        finally:
            reset_current_tenant(token_ctx)


def test_report_includes_risk_items_from_proctor_logs(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        interview_id, token = _seed_interviewing(client)
        headers = {"Authorization": f"Bearer {token}"}
        state0 = client.get(f"/api/interviews/{interview_id}/state", headers=headers).json()
        total = int(state0.get("totalQuestions") or 8)
        service = client.app.state.service
        token_ctx = set_current_tenant(DEFAULT_TENANT_ID)
        try:
            with service.database.unit_of_work() as connection:
                for _ in range(TAB_HIDDEN_REVIEW_THRESHOLD):
                    append_proctor_log(connection, interview_id, "tab_hidden", {"hidden": True})
                append_proctor_log(connection, interview_id, "answer_latency", {"latencyMs": 400})
        finally:
            reset_current_tenant(token_ctx)
        answer = (
            "我主导了实验模块，个人负责实现和验证，将处理耗时降低30%，并与协作方对齐验收标准。"
        )
        for _ in range(total + 4):
            state = client.get(f"/api/interviews/{interview_id}/state", headers=headers).json()
            if state["status"] in {"wrapping_up", "scoring", "report_ready"}:
                break
            turn = client.post(
                f"/api/interviews/{interview_id}/turns",
                headers={**headers, "Idempotency-Key": uuid4().hex},
                json={"action": "answer", "content": answer},
            )
            assert turn.status_code == 200, turn.text
        finish = client.post(f"/api/interviews/{interview_id}/finish", headers=headers, json={})
        assert finish.status_code == 200, finish.text
        scored = client.post(f"/api/interviews/{interview_id}/score", json={})
        assert scored.status_code == 200, scored.text
        body = scored.json()
        assert "riskItems" in body
        codes = {item["code"] for item in body["riskItems"]}
        assert "excessive_tab_switch" in codes
        assert "answer_too_fast" in codes
        assert all(item.get("affectsScore") is False for item in body["riskItems"])
