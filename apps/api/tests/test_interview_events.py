"""Interview event-sourcing: seq uniqueness, monotonicity, replay, and transactional rollback."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from conftest import STRONG, begin, invitation
from interviewer import database as db, events
from interviewer.contracts import json_object
from interviewer.repository import SQLAlchemyRepository
from interviewer.settings import Settings


def _admin(client: TestClient) -> None:
    assert client.post("/api/admin/login", json={}).status_code == 200


def _seed_interview(connection: object) -> str:
    job = db.insert(connection, db.jobs, {
        "title": "事件溯源岗位", "jd_text": "x" * 40, "status": "draft", "recruitment_track": "general",
    })
    person = db.insert(connection, db.candidates, {
        "job_id": str(job["id"]), "full_name": "合成", "retained_until": db.now(),
    })
    interview = db.insert(connection, db.interviews, {
        "candidate_id": str(person["id"]), "job_id": str(job["id"]), "status": "invited",
        "duration_minutes": 15, "retained_until": db.now(), "mode": "text", "locale": "zh-CN",
        "version": 0, "current_question_seq": 0, "paused_total_sec": 0,
        "camera_required": False, "camera_active": False, "microphone_active": False,
        "text_fallback": False, "recruitment_track": "general", "retention_days": 90,
    })
    return str(interview["id"])


def test_event_seq_monotonic_across_consent_start_and_turns(client: TestClient) -> None:
    created, _person = invitation(client)
    identity = str(created["interviewId"])
    headers = begin(client, created)
    response = client.post(
        f"/api/interviews/{identity}/turns",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"action": "answer", "content": STRONG},
    )
    assert response.status_code == 200, response.text
    _admin(client)
    payload = json_object(client.get(f"/api/admin/interviews/{identity}/events").json())
    seqs = [int(row["seq"]) for row in payload["events"]]
    assert seqs == list(range(1, len(seqs) + 1))
    types = [str(row["eventType"]) for row in payload["events"]]
    assert types[0] == "consent_granted"
    assert "state_changed" in types
    assert "question_asked" in types
    assert "answer_received" in types


def test_interview_events_unique_constraint_rejects_duplicate_seq(tmp_path: Path) -> None:
    path = tmp_path / "events-uq.sqlite3"
    database = db.Database(Settings(sqlite_path=str(path)))
    try:
        database.migrate()
        with database.unit_of_work() as connection:
            identity = _seed_interview(connection)
            events.append_event(connection, identity, "state_changed", {"to": "invited"})
        with pytest.raises(IntegrityError):
            with database.engine.begin() as raw:
                raw.execute(
                    db.interview_events.insert().values(
                        id=db.identifier(),
                        interview_id=identity,
                        seq=1,
                        event_type="state_changed",
                        payload={"dup": True},
                        ts=db.now(),
                    )
                )
    finally:
        database.close()


def test_fake_interview_events_replay_state_sequence(client: TestClient) -> None:
    created, _person = invitation(client)
    identity = str(created["interviewId"])
    headers = begin(client, created)
    for _ in range(40):
        response = client.post(
            f"/api/interviews/{identity}/turns",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={"action": "answer", "content": STRONG},
        )
        assert response.status_code == 200, response.text
        done = next(event for event in response.text.split("\n\n") if event.startswith("event: done\n"))
        body = json_object(json.loads(done.removeprefix("event: done\ndata: ")))
        if body.get("status") in {"wrapping_up", "scoring"} or body.get("kind") == "complete":
            break
    else:
        pytest.fail("interview did not reach wrapping_up")
    finish = client.post(f"/api/interviews/{identity}/finish", headers=headers, json={})
    assert finish.status_code == 200, finish.text
    score = client.post(f"/api/interviews/{identity}/score", json={})
    assert score.status_code == 200, score.text
    _admin(client)
    payload = json_object(client.get(f"/api/admin/interviews/{identity}/events").json())
    types = [str(row["eventType"]) for row in payload["events"]]
    assert types[0] == "consent_granted"
    assert "question_asked" in types
    assert "answer_received" in types
    assert "score_computed" in types
    assert "report_generated" in types
    statuses = ["invited"]
    for row in payload["events"]:
        if row["eventType"] != "state_changed":
            continue
        event_payload = row["payload"] if isinstance(row["payload"], dict) else {}
        nxt = event_payload.get("to")
        if nxt:
            statuses.append(str(nxt))
    assert "interviewing" in statuses
    assert "scoring" in statuses or "wrapping_up" in statuses
    assert "report_ready" in statuses
    seqs = [int(row["seq"]) for row in payload["events"]]
    assert seqs == list(range(1, len(seqs) + 1))


def test_event_not_persisted_when_business_write_rolls_back(tmp_path: Path) -> None:
    path = tmp_path / "events-tx.sqlite3"
    database = db.Database(Settings(sqlite_path=str(path)))
    try:
        database.migrate()
        with database.unit_of_work() as connection:
            identity = _seed_interview(connection)
        try:
            with database.transaction() as raw:
                events.append_event(SQLAlchemyRepository(raw), identity, "state_changed", {"to": "interviewing"})
                raise RuntimeError("force_rollback")
        except RuntimeError:
            pass
        with database.engine.connect() as connection:
            count = connection.execute(
                text("SELECT COUNT(*) FROM interview_events WHERE interview_id = :id"),
                {"id": identity},
            ).scalar()
        assert int(str(count or 0)) == 0
    finally:
        database.close()


def test_pause_emits_state_changed_event(client: TestClient) -> None:
    created, _person = invitation(client)
    identity = str(created["interviewId"])
    headers = begin(client, created)
    assert client.post(f"/api/interviews/{identity}/pause", headers=headers, json={"paused": True}).status_code == 200
    assert client.post(f"/api/interviews/{identity}/pause", headers=headers, json={"paused": False}).status_code == 200
    _admin(client)
    types = [str(row["eventType"]) for row in json_object(client.get(f"/api/admin/interviews/{identity}/events").json())["events"]]
    assert types.count("state_changed") >= 3
