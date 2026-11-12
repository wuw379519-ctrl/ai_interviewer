from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, TypeAdapter
from sqlalchemy import DateTime, JSON, Uuid, func, select

from . import database as db
from .contracts import Contract, Object
from .storage_types import PortableJSON, UTCDateTime


class Snapshot(Contract):
    format: Literal["aii-snapshot-v1"]
    created_at: str
    tables_json: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def encode_snapshot(database: db.Database) -> str:
    """For migration tests/backup tooling, never printed by the ordinary API."""
    with database.transaction() as connection:
        tables = {name: db.rows(connection, select(table)) for name, table in db.TABLES.items()}
    payload = json.dumps(tables, ensure_ascii=False, separators=(",", ":"), default=lambda value: db.iso(value))
    return Snapshot(format="aii-snapshot-v1", created_at=db.iso(db.now()), tables_json=payload,
                    sha256=hashlib.sha256(payload.encode()).hexdigest()).model_dump_json(by_alias=True)


def import_snapshot(database: db.Database, file: Path, quarantine_unconsented: bool = False) -> Object:
    snapshot = Snapshot.model_validate_json(file.read_bytes())
    if not hmac.compare_digest(hashlib.sha256(snapshot.tables_json.encode()).hexdigest(), snapshot.sha256):
        raise ValueError("快照校验失败；未导入任何数据")
    tables = TypeAdapter(dict[str, list[dict[str, object]]]).validate_json(snapshot.tables_json)
    if set(tables) != set(db.TABLES):
        raise ValueError("快照表集合不匹配；请先用原系统升级并导出完整15张业务表")
    consents = {str(row["interview_id"]) for row in tables["consents"] if row.get("consent_version") and row.get("consent_text_hash")}
    unconsented = {str(row["interview_id"]) for row in tables["turns"] if row.get("role") == "candidate" and str(row["interview_id"]) not in consents}
    quarantine_file: Path | None = None
    if unconsented:
        if not quarantine_unconsented:
            raise ValueError("历史回答缺少版本化同意记录，拒绝导入；可显式隔离旧场次，原库未改动")
        # Preserve the entire original envelope offline, including all excluded history.
        # Never invent consent or expose these answers in the new application.
        quarantine_file = file.with_suffix(".quarantine.json")
        excluded = set(unconsented)
        for name in ["questions", "turns", "evidence", "scores", "reports", "consents"]:
            excluded.update(str(row["id"]) for row in tables[name] if str(row.get("interview_id")) in unconsented)
        for name, entries in tables.items():
            if name in {"jobs", "competencies", "candidates", "resumes", "data_policies"}:
                continue
            # Also quarantine caches and audit payloads mentioning any excluded graph ID.
            tables[name] = [row for row in entries if not any(identity in json.dumps(row, ensure_ascii=False) for identity in excluded)]
    converted: dict[str, list[db.Row]] = {}
    for name, entries in tables.items():
        columns = db.TABLES[name].c
        converted[name] = []
        for entry in entries:
            if not set(entry) <= set(columns.keys()):
                raise ValueError(f"快照包含未知列：{name}")
            row: db.Row = {}
            for key, value in entry.items():
                column = columns[key]
                if value is not None and isinstance(column.type, (DateTime, UTCDateTime)):
                    value = db.utc(value)
                elif value is not None and isinstance(column.type, Uuid):
                    value = str(UUID(str(value)))
                elif value is not None and isinstance(column.type, (JSON, PortableJSON)):
                    value = TypeAdapter(object).validate_json(json.dumps(value, ensure_ascii=False))
                row[key] = value
            converted[name].append(row)
    with database.transaction() as connection:
        seed_tables = {"data_policies", "tenants", "users", "role_bindings"}
        if any(db.scalar(connection, select(func.count()).select_from(table))
               for name, table in db.TABLES.items() if name not in seed_tables):
            raise ValueError("目标数据库非空，拒绝覆盖；请使用独立空库")
        if quarantine_file:
            descriptor = os.open(quarantine_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(file.read_bytes())
        # Import is an offline, exclusive, atomic copy of pre-existing consented history.
        # Only the new-answer gate is suspended in this transaction; evidence/FKs remain enforced.
        # Restore the identical gate before commit. Other connections never see an unguarded committed schema.
        with database.historical_answer_import(connection):
            db.command(connection, db.data_policies.delete())
            # Preserve seeded tenancy rows; wipe only if the snapshot supplies replacements.
            for name in ("role_bindings", "users", "tenants"):
                if converted.get(name):
                    db.command(connection, db.TABLES[name].delete())
            for table in db.TABLES.values():
                for row in converted.get(table.name, []):
                    db.insert(connection, table, row)
        db.insert(connection, db.audit_logs, {"actor_type": "system", "actor_id": "python-migration", "action": "migration.imported",
                  "metadata": {"format": snapshot.format, "counts": {name: len(rows) for name, rows in tables.items()}, "quarantinedInterviews": len(unconsented)}})
    return {"imported": True, "counts": {name: len(rows) for name, rows in tables.items()}, "sourceUnchanged": True,
            "quarantinedInterviews": len(unconsented), "quarantineFile": str(quarantine_file) if quarantine_file else None}
