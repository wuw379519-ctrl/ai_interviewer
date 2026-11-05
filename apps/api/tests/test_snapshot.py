from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from interviewer import database as db
from interviewer.assessment import report_document
from interviewer.cli import seed
from interviewer.service import Service, object_value
from interviewer.settings import Settings
from interviewer.snapshot import encode_snapshot, import_snapshot


def test_offline_copy_preserves_history_ids_and_restores_consent_gate(tmp_path: Path) -> None:
    settings = Settings(sqlite_path=":memory:", secret="fixture-" * 8)
    source = db.Database(settings)
    source.migrate()
    service = Service(settings, source)
    result = seed(service)
    assert result["jobs"] == 3 and result["candidates"] == 9 and result["interviews"] == 4
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(encode_snapshot(source), encoding="utf-8")
    target = db.Database(settings)
    target.migrate()
    try:
        imported = import_snapshot(target, snapshot)
        assert imported["sourceUnchanged"] is True
        with source.transaction() as a, target.transaction() as b:
            original = db.rows(a, select(db.interviews).where(db.interviews.c.status == "report_ready"))[0]
            copied = db.one(b, db.interviews, str(original["id"]))
            assert copied == original
            document = report_document(Service(settings, target), b, str(original["id"]))
            assert len(document["evidence"]) == 8
        with pytest.raises(IntegrityError, match="candidate_consent_gate"), target.transaction() as connection:
            invited = db.rows(connection, select(db.interviews).where(db.interviews.c.status == "invited"))[0]
            db.insert(connection, db.turns, {"interview_id": invited["id"], "seq": 1, "role": "candidate", "content": "不得写入"})
        with pytest.raises(ValueError, match="非空"):
            import_snapshot(target, snapshot)
    finally:
        source.close()
        target.close()


def test_snapshot_checksum_failure_has_no_side_effects(tmp_path: Path) -> None:
    settings = Settings(sqlite_path=":memory:")
    database = db.Database(settings)
    database.migrate()
    file = tmp_path / "bad.json"
    file.write_text('{"format":"aii-snapshot-v1","createdAt":"fixture","tablesJson":"{}","sha256":"' + "0" * 64 + '"}', encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="校验失败"):
            import_snapshot(database, file)
        with database.transaction() as connection:
            assert db.rows(connection, select(db.jobs)) == []
    finally:
        database.close()


def test_seed_does_not_reset_existing_data(client: TestClient) -> None:
    service = client.app.state.service
    result = seed(service)
    assert result["seeded"] is True
    assert seed(service)["seeded"] is False
    with service.database.transaction() as connection:
        assert len(db.rows(connection, select(db.jobs))) == 3
        assert object_value(service.policy(connection))["retentionDays"] == 90


def test_missing_historical_consent_is_quarantined_without_fabrication(tmp_path: Path) -> None:
    settings = Settings(sqlite_path=":memory:", secret="fixture-" * 8)
    source, target = db.Database(settings), db.Database(settings)
    source.migrate()
    target.migrate()
    try:
        seed(Service(settings, source))
        with source.transaction() as connection:
            active = db.rows(connection, select(db.interviews).where(db.interviews.c.status == "report_ready"))[0]
            connection.execute(db.consents.delete().where(db.consents.c.interview_id == active["id"]))
        snapshot = tmp_path / "source.json"
        snapshot.write_text(encode_snapshot(source), encoding="utf-8")
        with pytest.raises(ValueError, match="缺少"):
            import_snapshot(target, snapshot)
        result = import_snapshot(target, snapshot, quarantine_unconsented=True)
        assert result["quarantinedInterviews"] == 1
        assert snapshot.with_suffix(".quarantine.json").read_bytes() == snapshot.read_bytes()
        with source.transaction() as original, target.transaction() as migrated:
            assert len(db.rows(original, select(db.interviews))) == 4
            assert len(db.rows(migrated, select(db.interviews))) == 3
            assert not db.one(migrated, db.interviews, str(active["id"]))
    finally:
        source.close()
        target.close()
