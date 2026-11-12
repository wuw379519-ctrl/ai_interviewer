"""Commit 1: tenants schema, default backfill, get_current_tenant from session."""
from __future__ import annotations

from pathlib import Path

from fastapi import Request
from sqlalchemy import select, text

from interviewer import database as db
from interviewer.auth import Actor
from interviewer.settings import Settings
from interviewer.tenancy import DEFAULT_TENANT_ID, get_current_tenant, get_current_user

TENANT_BACKFILL_TABLES = (
    "jobs", "candidates", "competencies", "interviews", "questions", "turns", "evidence",
    "scores", "score_revisions", "reports", "consents", "resumes", "idempotency_keys",
    "data_policies", "audit_logs", "interview_events", "practice_sessions",
)


def test_default_tenant_seeded_and_business_rows_backfilled(tmp_path: Path) -> None:
    path = tmp_path / "tenancy.sqlite3"
    database = db.Database(Settings(sqlite_path=str(path)))
    try:
        database.migrate()
        with database.engine.connect() as connection:
            tenants = connection.execute(text("SELECT id, name, status FROM tenants")).fetchall()
            assert any(str(row[0]) == DEFAULT_TENANT_ID and str(row[1]) == "default" for row in tenants)
            users = connection.execute(text("SELECT external_key FROM users")).fetchall()
            assert {"admin", "recruiter"} <= {str(row[0]) for row in users}
            bindings = connection.execute(text("SELECT role FROM role_bindings")).fetchall()
            assert {"admin", "recruiter"} <= {str(row[0]) for row in bindings}
            for table in TENANT_BACKFILL_TABLES:
                nulls = connection.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id IS NULL")
                ).scalar()
                assert int(str(nulls or 0)) == 0, table
            # data_policies workspace row exists and is on default tenant
            policy = connection.execute(
                text("SELECT tenant_id FROM data_policies WHERE id = 'workspace'")
            ).scalar()
            assert str(policy) == DEFAULT_TENANT_ID
            usage_nulls = connection.execute(
                text("SELECT COUNT(*) FROM ai_usage WHERE tenant IS NULL")
            ).scalar()
            assert int(str(usage_nulls or 0)) == 0
    finally:
        database.close()


def test_get_current_tenant_from_authenticated_actor() -> None:
    request = Request({"type": "http", "headers": [], "method": "GET", "path": "/api/admin/interviews"})
    request.state.actor = Actor("admin", "admin", "工作空间管理员", DEFAULT_TENANT_ID)
    assert get_current_tenant(request) == DEFAULT_TENANT_ID
    assert get_current_user(request).role == "admin"


def test_new_job_insert_gets_default_tenant(tmp_path: Path) -> None:
    path = tmp_path / "tenancy-insert.sqlite3"
    database = db.Database(Settings(sqlite_path=str(path)))
    try:
        database.migrate()
        with database.unit_of_work() as connection:
            job = db.insert(connection, db.jobs, {
                "title": "租户岗位", "jd_text": "x" * 40, "status": "draft", "recruitment_track": "general",
            })
            row = db.one(connection, db.jobs, str(job["id"]))
            assert row is not None
            assert str(row["tenant_id"]) == DEFAULT_TENANT_ID
            found = db.rows(connection, select(db.tenants).where(db.tenants.c.id == DEFAULT_TENANT_ID))
            assert found and str(found[0]["name"]) == "default"
    finally:
        database.close()
