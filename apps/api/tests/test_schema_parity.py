"""SQLite and Postgres migration chains must converge on the same business schema."""
from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from interviewer import database as db
from interviewer.schema_inventory import (
    BUSINESS_TABLES,
    REQUIRED_COLUMNS,
    assert_matches_canonical,
    collect_schema,
)
from interviewer.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
SQLITE_MIGRATIONS = ROOT / "apps" / "api" / "migrations" / "sqlite"
POSTGRES_MIGRATIONS = ROOT / "apps" / "api" / "migrations" / "postgres"
EXPECTED_SQLITE_FILES = (
    "0001_initial.sql",
    "0002_practice_sessions.sql",
    "0003_supporting_indexes.sql",
    "0004_integrity_guards.sql",
    "0005_interview_events.sql",
)


def _pragma_columns(connection: object, table: str) -> dict[str, bool]:
    rows = connection.execute(text(f"PRAGMA table_info('{table}')")).fetchall()
    # cid, name, type, notnull, dflt_value, pk
    return {str(row[1]): not bool(row[3]) for row in rows}


def test_sqlite_migrate_builds_canonical_schema(tmp_path: Path) -> None:
    path = tmp_path / "parity.sqlite3"
    database = db.Database(Settings(sqlite_path=str(path)))
    try:
        database.migrate()
        snapshot = collect_schema(database.engine, postgres=False)
        problems = assert_matches_canonical(snapshot)
        assert problems == [], problems
        with database.engine.connect() as connection:
            applied = {
                str(row[0])
                for row in connection.execute(text("SELECT id FROM __python_migrations")).fetchall()
            }
            for name in EXPECTED_SQLITE_FILES:
                assert name in applied, name
            for table, expected in REQUIRED_COLUMNS.items():
                pragma = _pragma_columns(connection, table)
                assert set(expected) <= set(pragma), f"{table} pragma missing {set(expected) - set(pragma)}"
                for column, nullable in expected.items():
                    assert pragma[column] == nullable, (
                        f"{table}.{column} pragma nullability want={nullable} got={pragma[column]}"
                    )
            master = " ".join(
                str(row[0] or "")
                for row in connection.execute(
                    text("SELECT sql FROM sqlite_master WHERE type IN ('trigger','table','index')")
                ).fetchall()
            ).lower()
            for token in (
                "candidate_answer_gate",
                "evidence_quote_gate",
                "jobs_status_valid",
                "interviews_status_valid",
                "turns_role_valid",
                "reports_recommendation_valid",
                "questions_assessment_mode_valid",
                "interviews_recruitment_track_valid",
                "erased_at is null or deleted_at is not null",
                "audit_logs_action_idx",
                "candidates_erased_at_idx",
            ):
                assert token in master, token
    finally:
        database.close()


def test_sqlite_cli_migrate_on_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "cli-empty.sqlite3"
    assert not path.exists()
    database = db.Database(Settings(sqlite_path=str(path)))
    try:
        database.migrate()
        assert path.exists()
        snapshot = collect_schema(database.engine, postgres=False)
        assert assert_matches_canonical(snapshot) == []
    finally:
        database.close()


def test_sqlite_migration_files_are_append_only_and_parseable() -> None:
    files = sorted(SQLITE_MIGRATIONS.glob("*.sql"))
    names = [file.name for file in files]
    assert names == list(EXPECTED_SQLITE_FILES), names
    for file in files:
        content = file.read_text(encoding="utf-8")
        assert content.strip(), file.name
        # Each statement chunk must be non-empty SQL after splitting the project breakpoint marker.
        chunks = [part.strip() for part in content.split("-- statement-breakpoint") if part.strip()]
        assert chunks, file.name
        for chunk in chunks:
            assert not chunk.lower().startswith("drop table"), f"destructive DDL in {file.name}"


def test_postgres_migration_chain_present_and_immutable_naming() -> None:
    names = sorted(path.name for path in POSTGRES_MIGRATIONS.glob("*.sql"))
    assert names[0] == "0000_init.sql"
    assert names[-1] == "0011_interview_events.sql"
    assert len(names) == 12
    for name in names:
        assert re.fullmatch(r"\d{4}_[a-z0-9_]+\.sql", name), name


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires disposable Postgres16")
def test_postgres_migrate_matches_same_canonical_inventory() -> None:
    database = db.Database(Settings(database_url=os.environ["TEST_DATABASE_URL"]))
    schema = "parity_" + uuid4().hex
    try:
        with database.engine.begin() as connection:
            version = int(str(connection.execute(text("SHOW server_version_num")).scalar_one()))
            if not 160000 <= version < 170000:
                pytest.skip("parity requires PostgreSQL16")
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
        snapshot = collect_schema(database.engine, postgres=True)
        problems = assert_matches_canonical(snapshot)
        assert problems == [], problems
        # Cross-check column inventory against a fresh SQLite migrate of the same revision.
        sqlite = db.Database(Settings(sqlite_path=":memory:"))
        try:
            sqlite.migrate()
            sqlite_snapshot = collect_schema(sqlite.engine, postgres=False)
            assert BUSINESS_TABLES <= snapshot.tables
            assert BUSINESS_TABLES <= sqlite_snapshot.tables
            for table in BUSINESS_TABLES:
                assert snapshot.columns[table].keys() == sqlite_snapshot.columns[table].keys()
                for name, nullable in sqlite_snapshot.columns[table].items():
                    assert snapshot.columns[table][name] == nullable, (
                        f"{table}.{name} nullability diverged "
                        f"sqlite={nullable} pg={snapshot.columns[table][name]}"
                    )
            with database.engine.connect() as connection:
                for table, expected in REQUIRED_COLUMNS.items():
                    rows = connection.execute(text(
                        "SELECT column_name, is_nullable FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = :table"
                    ), {"table": table}).fetchall()
                    info = {str(row[0]): str(row[1]).upper() == "YES" for row in rows}
                    for column, nullable in expected.items():
                        assert column in info, f"pg missing {table}.{column}"
                        assert info[column] == nullable, (
                            f"pg {table}.{column} nullability want={nullable} got={info[column]}"
                        )
        finally:
            sqlite.close()
    finally:
        assert schema.startswith("parity_") and len(schema) == 39
        with database.engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        database.close()
