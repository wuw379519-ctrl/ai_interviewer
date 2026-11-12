"""Commit 3: PostgreSQL RLS — requires disposable TEST_DATABASE_URL; otherwise skip.

Superusers bypass RLS even with FORCE; tests SET ROLE to a NOSUPERUSER/NOBYPASSRLS
role. Production DATABASE_URL must likewise use a non-bypass role (see D72).
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from interviewer import database as db
from interviewer.settings import Settings
from interviewer.tenancy import DEFAULT_TENANT_ID

TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
APP_ROLE = "aii_rls_app"

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="requires disposable Postgres16+ (TEST_DATABASE_URL); SQLite has no RLS",
)


@pytest.fixture
def pg_database() -> Iterator[tuple[db.Database, str]]:
    database = db.Database(Settings(database_url=os.environ["TEST_DATABASE_URL"]))
    schema = "rls_" + uuid4().hex
    try:
        with database.engine.begin() as connection:
            version = int(str(connection.execute(text("SHOW server_version_num")).scalar_one()))
            if version < 160000:
                pytest.skip("RLS integration requires PostgreSQL >= 16")
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    except OperationalError:
        database.close()
        pytest.skip("explicit disposable PostgreSQL test service unavailable")
    database.engine.dispose()

    def search_path(raw: object, _record: object) -> None:
        import psycopg

        assert isinstance(raw, psycopg.Connection)
        with raw.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema}"')
        raw.commit()

    event.listen(database.engine, "connect", search_path)
    try:
        database.migrate()
        with database.engine.begin() as connection:
            connection.execute(text(
                f"DO $$ BEGIN CREATE ROLE {APP_ROLE} NOSUPERUSER NOBYPASSRLS NOINHERIT; "
                f"EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            ))
            connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO {APP_ROLE}'))
            connection.execute(text(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO {APP_ROLE}'
            ))
            # Table owner remains the migrator; FORCE RLS still applies to APP_ROLE.
        yield database, schema
    finally:
        assert schema.startswith("rls_") and len(schema) == 36
        with database.engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        database.close()


def _as_app(connection: object, tenant_id: str) -> None:
    connection.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))  # type: ignore[union-attr]
    connection.execute(  # type: ignore[union-attr]
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id}
    )


def test_rls_hides_rows_without_matching_tenant_guc(pg_database: tuple[db.Database, str]) -> None:
    database, _schema = pg_database
    with database.engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO tenants (id, name, status) VALUES (:id, :name, 'active') "
            "ON CONFLICT (id) DO NOTHING"
        ), {"id": TENANT_A, "name": "rls-a"})
        connection.execute(text(
            "INSERT INTO tenants (id, name, status) VALUES (:id, :name, 'active') "
            "ON CONFLICT (id) DO NOTHING"
        ), {"id": TENANT_B, "name": "rls-b"})
        # Insert as table owner (bypass) so seed is visible; RLS checked via SET ROLE.
        connection.execute(text(
            "INSERT INTO jobs (id, title, jd_text, status, recruitment_track, tenant_id) "
            "VALUES (gen_random_uuid(), 'RLS-A', :jd, 'draft', 'general', :tid)"
        ), {"jd": "x" * 40, "tid": TENANT_A})

    with database.engine.begin() as connection:
        _as_app(connection, TENANT_A)
        visible = connection.execute(text("SELECT count(*) FROM jobs WHERE title = 'RLS-A'")).scalar()
        assert int(str(visible or 0)) == 1

    with database.engine.begin() as connection:
        _as_app(connection, TENANT_B)
        hidden = connection.execute(text("SELECT count(*) FROM jobs WHERE title = 'RLS-A'")).scalar()
        assert int(str(hidden or 0)) == 0

    with database.engine.begin() as connection:
        _as_app(connection, TENANT_A)
        again = connection.execute(text("SELECT count(*) FROM jobs WHERE title = 'RLS-A'")).scalar()
        assert int(str(again or 0)) == 1


def test_rls_empty_guc_hides_default_tenant_rows(pg_database: tuple[db.Database, str]) -> None:
    database, _schema = pg_database
    with database.engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO jobs (id, title, jd_text, status, recruitment_track, tenant_id) "
            "VALUES (gen_random_uuid(), 'default-visible', :jd, 'draft', 'general', :tid)"
        ), {"jd": "x" * 40, "tid": DEFAULT_TENANT_ID})

    with database.engine.begin() as connection:
        _as_app(connection, DEFAULT_TENANT_ID)
        present = connection.execute(text("SELECT count(*) FROM jobs WHERE title = 'default-visible'")).scalar()
        assert int(str(present or 0)) == 1

    with database.engine.begin() as connection:
        connection.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))
        connection.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        count = connection.execute(text("SELECT count(*) FROM jobs")).scalar()
        assert int(str(count or 0)) == 0
