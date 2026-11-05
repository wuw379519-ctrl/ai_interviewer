"""Same assertions for SQLite memory/file and explicitly supplied disposable PG16."""
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import ast
import os

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import OperationalError, StatementError

from interviewer import database as db
from interviewer.repository import repository
from interviewer.settings import ROOT, Settings


@pytest.fixture(params=["sqlite-memory", "sqlite-file", "postgres"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[db.Database]:
    if request.param == "postgres":
        url = os.getenv("TEST_DATABASE_URL")
        if not url:
            pytest.skip("TEST_DATABASE_URL not supplied; no non-test database is contacted")
        database = db.Database(Settings(database_url=url))
        schema = "contract_" + uuid4().hex
        try:
            with database.engine.begin() as connection:
                version = int(str(connection.execute(text("SHOW server_version_num")).scalar_one()))
                if not 160000 <= version < 170000:
                    pytest.skip("contract requires PostgreSQL16")
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
    else:
        database = db.Database(Settings(sqlite_path=":memory:" if request.param == "sqlite-memory" else str(tmp_path / "contract.sqlite3")))
        schema = None
    try:
        database.migrate()
        yield database
    finally:
        if schema:
            # Only this UUID-named test schema is dropped; never public or an existing schema.
            assert schema.startswith("contract_") and len(schema) == 41
            with database.engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        database.close()


def test_utc_offset_and_boolean_round_trip(store: db.Database) -> None:
    local = datetime(2026, 1, 2, 8, 30, tzinfo=timezone(timedelta(hours=8)))
    with store.unit_of_work() as session:
        row = db.insert(session, db.audit_logs, {"actor_type": "system", "action": "contract.clock", "created_at": local, "metadata": {"enabled": True}})
        assert row["created_at"] == datetime(2026, 1, 2, 0, 30, tzinfo=UTC)
        assert row["metadata"] == {"enabled": True}


def test_json_null_arrays_and_object_semantics(store: db.Database) -> None:
    value = {"b": [None, True, False, 1, "研究"], "a": {"nested": None}}
    with store.unit_of_work() as session:
        row = db.insert(session, db.audit_logs, {"actor_type": "system", "action": "contract.json", "metadata": value})
        assert row["metadata"] == value
        db.update(session, db.audit_logs, str(row["id"]), metadata=None)
        assert db.one(session, db.audit_logs, str(row["id"]))["metadata"] is None


@pytest.mark.parametrize("invalid", [{"number": float("nan")}, {"nested": ["\x00"]}, {1: "nonstring key"}])
def test_invalid_json_is_rejected_consistently_without_partial_write(store: db.Database, invalid: object) -> None:
    identity = str(uuid4())
    with pytest.raises(StatementError), store.unit_of_work() as session:
        db.insert(session, db.audit_logs, {"id": identity, "actor_type": "system", "action": "contract.invalid_json", "metadata": invalid})
    with store.unit_of_work() as session:
        assert db.one(session, db.audit_logs, identity) is None


def test_unique_conflict_does_not_replace_or_abort_transaction(store: db.Database) -> None:
    with store.unit_of_work() as session:
        assert not session.insert_if_absent(db.data_policies, {"id": "workspace", "retention_days": 30, "revision": 99}, ["id"])
        assert db.one(session, db.data_policies, "workspace")["retention_days"] == 90
        row = db.insert(session, db.audit_logs, {"actor_type": "system", "action": "contract.after_conflict", "metadata": {}})
        assert db.one(session, db.audit_logs, str(row["id"])) is not None


def test_transaction_rollback_preserves_prior_state(store: db.Database) -> None:
    identity = str(uuid4())
    with pytest.raises(RuntimeError, match="rollback"), store.unit_of_work() as session:
        db.insert(session, db.audit_logs, {"id": identity, "actor_type": "system", "action": "contract.rollback", "metadata": {}})
        raise RuntimeError("rollback")
    with store.unit_of_work() as session:
        assert db.one(session, db.audit_logs, identity) is None
        assert len(session.rows(select(db.data_policies))) == 1
        assert repository(session) is session


def test_online_business_has_no_driver_calls_or_sql_strings() -> None:
    for name in ["service", "assessment", "governance", "main", "speech"]:
        tree = ast.parse((ROOT / "apps/api/interviewer" / f"{name}.py").read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"exec_driver_sql", "execute", "executescript", "create_engine"}
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not node.value.lstrip().upper().startswith(("SELECT ", "INSERT INTO ", "UPDATE ", "DELETE FROM ", "PRAGMA "))


def test_mapping_matches_frozen_physical_types() -> None:
    from sqlalchemy.dialects import postgresql, sqlite
    assert db.jobs.c.created_at.type.compile(dialect=postgresql.dialect()) == "TIMESTAMP WITH TIME ZONE"
    assert db.jobs.c.created_at.type.compile(dialect=sqlite.dialect()) == "DATETIME"
    assert db.audit_logs.c.metadata.type.compile(dialect=postgresql.dialect()) == "JSONB"
    assert db.audit_logs.c.metadata.type.compile(dialect=sqlite.dialect()) == "JSON"
