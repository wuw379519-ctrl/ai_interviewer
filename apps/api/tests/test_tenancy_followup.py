"""Task 4 wrap-up: non-default policy gap + SQLite rls_role_is_safe noop."""
from __future__ import annotations

from pathlib import Path

from interviewer import database as db
from interviewer.contracts import CandidateCreate
from interviewer.errors import DomainError
from interviewer.service import Service
from interviewer.settings import Settings
from interviewer.tenancy import reset_current_tenant, set_current_tenant

TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_sqlite_rls_role_is_safe() -> None:
    database = db.Database(Settings(sqlite_path=":memory:"))
    try:
        database.migrate()
        ok, detail = database.rls_role_is_safe()
        assert ok is True and detail == "sqlite"
    finally:
        database.close()


def test_non_default_tenant_main_flow_blocked_by_data_policies(tmp_path: Path) -> None:
    """Isolation holds, but create_candidate needs policy() → NOT_READY without per-tenant row."""
    path = tmp_path / "followup.sqlite3"
    settings = Settings(sqlite_path=str(path), secret="fixture-" * 8)
    database = db.Database(settings)
    try:
        database.migrate()
        with database.unit_of_work() as connection:
            connection.insert_if_absent(
                db.tenants, {"id": TENANT_A, "name": "tenant-a", "status": "active"}, ["id"]
            )
            job = db.insert(connection, db.jobs, {
                "title": "非default岗位", "jd_text": "x" * 40, "status": "active",
                "recruitment_track": "general", "tenant_id": TENANT_A,
            })
            job_id = str(job["id"])

        service = Service(settings, database)
        token = set_current_tenant(TENANT_A)
        try:
            with database.unit_of_work() as connection:
                try:
                    service.policy(connection)
                    raise AssertionError("expected NOT_READY without per-tenant data_policies")
                except DomainError as error:
                    assert error.code == "NOT_READY"
                    assert error.status == 503
                try:
                    from interviewer.auth import Actor
                    service.create_candidate(
                        connection,
                        CandidateCreate(job_id=job_id, full_name="探测候选人"),
                        Actor("recruiter", "recruiter", "探测", TENANT_A),
                    )
                    raise AssertionError("create_candidate should fail before insert")
                except DomainError as error:
                    assert error.code == "NOT_READY"
                    assert error.status == 503
        finally:
            reset_current_tenant(token)
    finally:
        database.close()
