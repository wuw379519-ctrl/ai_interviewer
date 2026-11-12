"""Commit 2: application-layer tenant isolation — cross-tenant → 404, lists scoped, admin=default."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from interviewer import database as db
from interviewer.auth import Actor
from interviewer.errors import DomainError
from interviewer.main import create_app
from interviewer.service import Service
from interviewer.settings import Settings
from interviewer.tenancy import (
    DEFAULT_TENANT_ID,
    current_tenant,
    reset_current_tenant,
    set_current_tenant,
)

TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _seed_tenant_job(connection: object, tenant_id: str, title: str) -> str:
    row = db.insert(connection, db.jobs, {  # type: ignore[arg-type]
        "title": title,
        "jd_text": "x" * 40,
        "status": "draft",
        "recruitment_track": "general",
        "tenant_id": tenant_id,
    })
    return str(row["id"])


def _ensure_tenants(database: db.Database) -> None:
    with database.unit_of_work() as connection:
        for tenant_id, name in ((TENANT_A, "tenant-a"), (TENANT_B, "tenant-b")):
            connection.insert_if_absent(
                db.tenants,
                {"id": tenant_id, "name": name, "status": "active"},
                ["id"],
            )


def test_cross_tenant_resource_returns_404_not_403(tmp_path: Path) -> None:
    path = tmp_path / "iso.sqlite3"
    settings = Settings(sqlite_path=str(path), secret="fixture-" * 8,
                        admin_key="fixture-admin", recruiter_key="fixture-recruiter")
    database = db.Database(settings)
    try:
        database.migrate()
        _ensure_tenants(database)
        with database.unit_of_work() as connection:
            job_a = _seed_tenant_job(connection, TENANT_A, "岗位A")
            job_b = _seed_tenant_job(connection, TENANT_B, "岗位B")

        service = Service(settings, database)
        token_a = set_current_tenant(TENANT_A)
        try:
            with database.unit_of_work() as connection:
                assert current_tenant() == TENANT_A
                found = service.required(connection, db.jobs, job_a, "JOB_NOT_FOUND")
                assert str(found["title"]) == "岗位A"
                try:
                    service.required(connection, db.jobs, job_b, "JOB_NOT_FOUND")
                    raise AssertionError("expected cross-tenant JOB_NOT_FOUND")
                except DomainError as error:
                    assert error.code == "JOB_NOT_FOUND"
                    assert error.status == 404
                jobs = db.rows(connection, select(db.jobs).where(db.jobs.c.tenant_id == current_tenant()))
                assert {str(row["id"]) for row in jobs} == {job_a}
        finally:
            reset_current_tenant(token_a)

        token_b = set_current_tenant(TENANT_B)
        try:
            with database.unit_of_work() as connection:
                jobs = db.rows(connection, select(db.jobs).where(db.jobs.c.tenant_id == current_tenant()))
                assert {str(row["id"]) for row in jobs} == {job_b}
                try:
                    service.required(connection, db.jobs, job_a, "JOB_NOT_FOUND")
                    raise AssertionError("tenant B must not see A")
                except DomainError as error:
                    assert error.status == 404
        finally:
            reset_current_tenant(token_b)
    finally:
        database.close()


def test_admin_default_tenant_cannot_see_other_tenants(tmp_path: Path) -> None:
    path = tmp_path / "admin-iso.sqlite3"
    settings = Settings(sqlite_path=str(path), secret="fixture-" * 8,
                        admin_key="fixture-admin", recruiter_key="fixture-recruiter")
    with TestClient(create_app(settings)) as client:
        service = client.app.state.service
        database = service.database
        _ensure_tenants(database)
        with database.unit_of_work() as connection:
            job_a = _seed_tenant_job(connection, TENANT_A, "隔离岗位A")
            job_b = _seed_tenant_job(connection, TENANT_B, "隔离岗位B")
            default_job = _seed_tenant_job(connection, DEFAULT_TENANT_ID, "默认岗位")

        assert client.post("/api/auth/login", json={}).status_code == 200
        dashboard = client.get("/api/jobs")
        assert dashboard.status_code == 200
        ids = {item["id"] for item in dashboard.json()["jobs"]}
        assert default_job in ids
        assert job_a not in ids
        assert job_b not in ids

        # Cross-tenant create against B's job → 404 (existence not leaked as 403).
        response = client.post(
            "/api/candidates",
            json={"jobId": job_b, "fullName": "跨租户探测"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_http_actor_tenant_scopes_lists(monkeypatch: object, tmp_path: Path) -> None:
    path = tmp_path / "http-iso.sqlite3"
    settings = Settings(sqlite_path=str(path), secret="fixture-" * 8,
                        admin_key="fixture-admin", recruiter_key="fixture-recruiter")
    with TestClient(create_app(settings)) as client:
        service = client.app.state.service
        _ensure_tenants(service.database)
        with service.database.unit_of_work() as connection:
            job_a = _seed_tenant_job(connection, TENANT_A, "HTTP-A")
            job_b = _seed_tenant_job(connection, TENANT_B, "HTTP-B")

        original = service.auth.role

        def role_for_a(request: object, role: str) -> Actor:
            actor = original(request, role)  # type: ignore[arg-type]
            return Actor(actor.role, actor.id, actor.name, TENANT_A)

        monkeypatch.setattr(service.auth, "role", role_for_a)  # type: ignore[attr-defined]
        # data_policies remains a default-tenant singleton; stub policy for non-default actors.
        monkeypatch.setattr(  # type: ignore[attr-defined]
            Service, "policy", lambda self, connection: {"retentionDays": 90, "revision": 1}
        )
        monkeypatch.setattr(  # type: ignore[attr-defined]
            Service, "policy_row", lambda self, connection: {
                "id": "workspace", "retention_days": 90, "revision": 1, "tenant_id": TENANT_A
            }
        )
        assert client.post("/api/auth/login", json={}).status_code == 200
        response = client.get("/api/jobs")
        assert response.status_code == 200
        ids = {item["id"] for item in response.json()["jobs"]}
        assert job_a in ids
        assert job_b not in ids

        blocked = client.post("/api/candidates", json={"jobId": job_b, "fullName": "不可见"})
        assert blocked.status_code == 404
        assert blocked.json()["error"]["code"] == "JOB_NOT_FOUND"
