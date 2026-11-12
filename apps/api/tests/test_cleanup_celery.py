"""Task 8a: retention cleanup dry-run / execute / preserve non-expired (incl. proctor_logs)."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from interviewer import database as db
from interviewer.auth import Actor
from interviewer.governance import retention_cleanup_batch
from interviewer.main import create_app
from interviewer.proctoring import append_proctor_log
from interviewer.settings import Settings
from interviewer.tenancy import DEFAULT_TENANT_ID, reset_current_tenant, set_current_tenant


def _app(tmp_path: Path) -> TestClient:
    settings = Settings(
        sqlite_path=str(tmp_path / "cleanup.sqlite3"),
        secret="fixture-" * 8,
        admin_key="fixture-admin",
        recruiter_key="fixture-recruiter",
        provider="fake",
    )
    return TestClient(create_app(settings))


def _seed_interview(client: TestClient) -> str:
    assert client.post("/api/auth/login", json={}).status_code == 200
    job = client.post(
        "/api/jobs",
        json={
            "title": "Cleanup" + uuid4().hex[:4],
            "jdText": "面向研发的岗位说明，负责实验系统实现、质量验证、协作与学习，以量化结果和个人贡献说明任务成效。",
            "recruitmentTrack": "general",
        },
    ).json()
    extracted = client.post(f"/api/jobs/{job['id']}/competencies:extract", json={}).json()
    client.patch(f"/api/jobs/{job['id']}/competencies", json={"competencies": extracted["competencies"]})
    person = client.post("/api/candidates", json={"jobId": job["id"], "fullName": "清理候选人"}).json()
    client.post(
        f"/api/candidates/{person['id']}/resume",
        json={"text": "技能Python；项目：我主导实验模块，个人负责实现和验证，将处理耗时降低30%。"},
    )
    invited = client.post(
        "/api/interviews",
        json={
            "jobId": job["id"],
            "candidateId": person["id"],
            "durationMinutes": 15,
            "mode": "text",
            "cameraRequired": False,
        },
    ).json()
    return str(invited["interviewId"])


def test_cleanup_dry_run_execute_and_preserve_fresh(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        expired_id = _seed_interview(client)
        keep_id = _seed_interview(client)
        service = client.app.state.service
        actor = Actor("admin", "test-cleanup", "fixture", DEFAULT_TENANT_ID)
        token = set_current_tenant(DEFAULT_TENANT_ID)
        try:
            with service.database.unit_of_work() as connection:
                append_proctor_log(connection, expired_id, "tab_hidden", {"hidden": True})
                append_proctor_log(connection, keep_id, "tab_hidden", {"hidden": True})
                past = db.now() - timedelta(days=1)
                future = db.now() + timedelta(days=30)
                db.command(
                    connection,
                    db.interviews.update()
                    .where(db.interviews.c.id == expired_id)
                    .values(retained_until=past),
                )
                db.command(
                    connection,
                    db.interviews.update()
                    .where(db.interviews.c.id == keep_id)
                    .values(retained_until=future),
                )

                dry = retention_cleanup_batch(service, connection, actor, dry_run=True)
                assert dry["dryRun"] is True
                assert expired_id in dry["interviewIds"]
                assert keep_id not in dry["interviewIds"]
                assert dry["counts"]["proctorLogs"] >= 1
                assert len(db.rows(
                    connection,
                    select(db.proctor_logs).where(db.proctor_logs.c.interview_id == expired_id),
                )) >= 1

                executed = retention_cleanup_batch(service, connection, actor, dry_run=False)
                assert executed["dryRun"] is False
                assert executed["interviewsErased"] >= 1
                assert db.rows(
                    connection,
                    select(db.proctor_logs).where(db.proctor_logs.c.interview_id == expired_id),
                ) == []
                assert db.one(connection, db.interviews, expired_id) is None
                assert db.one(connection, db.interviews, keep_id) is not None
                assert len(db.rows(
                    connection,
                    select(db.proctor_logs).where(db.proctor_logs.c.interview_id == keep_id),
                )) >= 1
        finally:
            reset_current_tenant(token)


def test_celery_cleanup_task_eager_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "celery-cleanup.sqlite3"
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "true")
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    monkeypatch.setenv("DB_DRIVER", "sqlite")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("AUTH_SECRET", "fixture-" * 8)
    # Ensure schema exists before the task opens Settings.from_env().
    Settings(sqlite_path=str(db_path), secret="fixture-" * 8, provider="fake")
    from interviewer.database import Database

    database = Database(Settings(sqlite_path=str(db_path), secret="fixture-" * 8, provider="fake"))
    database.migrate()
    database.close()

    from interviewer.workers.celery_app import celery_app

    celery_app.conf.task_always_eager = True
    from interviewer.workers.tasks_cleanup import run_retention_cleanup

    result = run_retention_cleanup(dry_run=True)
    assert result["dryRun"] is True
    assert "counts" in result
