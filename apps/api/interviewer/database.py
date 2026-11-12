from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (Boolean, CheckConstraint, Column, Float, ForeignKey,
                        ForeignKeyConstraint, Integer, MetaData, String, Table, Text,
                        UniqueConstraint, Uuid, create_engine, event, func, select, text)
from sqlalchemy.engine import Connection
from .repository import StorageSession, SQLAlchemyRepository, repository
from .storage_types import PortableJSON, UTCDateTime
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import SchemaItem
from sqlalchemy.sql import Executable

from .settings import ROOT, Settings
from .tenancy import DEFAULT_TENANT_ID, current_tenant

Row = dict[str, object]
metadata = MetaData()


def now() -> datetime:
    return datetime.now(UTC)


def identifier() -> str:
    return str(uuid4())


def utc(value: object) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def iso(value: object) -> str:
    return utc(value).isoformat().replace("+00:00", "Z")


def uid(name: str = "id", target: str | None = None, nullable: bool = False,
        ondelete: str = "CASCADE") -> Column[str]:
    args = [ForeignKey(target, ondelete=ondelete)] if target else []
    return Column(name, Uuid(as_uuid=False), *args, nullable=nullable,
                  primary_key=name == "id", default=identifier if name == "id" else None)


def txt(name: str, default: str | None = None, nullable: bool = True) -> Column[str]:
    return Column(name, Text, nullable=nullable, default=default)


def integer(name: str, default: int | None = 0, nullable: bool = False) -> Column[int]:
    # Nullable integers must default to NULL; a zero default breaks offset/evidence CHECKs.
    return Column(name, Integer, nullable=nullable, default=None if nullable else default)


def boolean(name: str, default: bool = False) -> Column[bool]:
    return Column(name, Boolean, nullable=False, default=default)


def date(name: str, nullable: bool = True) -> Column[datetime]:
    return Column(name, UTCDateTime(), nullable=nullable)


def document(name: str, nullable: bool = False) -> Column[object]:
    return Column(name, PortableJSON(), nullable=nullable)


def table(name: str, *columns: SchemaItem) -> Table:
    return Table(name, metadata, *columns,
                 Column("created_at", UTCDateTime(), nullable=False, default=now, server_default=func.now()),
                 Column("updated_at", UTCDateTime(), nullable=False, default=now, onupdate=now, server_default=func.now()))


def tenant_id_column() -> Column[str]:
    return Column(
        "tenant_id",
        String(36),
        ForeignKey("tenants.id"),
        nullable=True,
        default=DEFAULT_TENANT_ID,
    )


tenants = table(
    "tenants",
    Column("id", String(36), primary_key=True, default=identifier),
    txt("name", nullable=False),
    txt("status", "active", False),
    UniqueConstraint("name"),
    CheckConstraint("status IN ('active','suspended','closed')"),
)
users = table(
    "users",
    Column("id", String(36), primary_key=True, default=identifier),
    Column("tenant_id", String(36), ForeignKey("tenants.id"), nullable=False),
    txt("external_key", nullable=False),
    txt("display_name"),
    txt("status", "active", False),
    UniqueConstraint("tenant_id", "external_key"),
    CheckConstraint("status IN ('active','disabled')"),
)
role_bindings = table(
    "role_bindings",
    Column("id", String(36), primary_key=True, default=identifier),
    Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column("tenant_id", String(36), ForeignKey("tenants.id"), nullable=False),
    txt("role", nullable=False),
    UniqueConstraint("user_id", "tenant_id", "role"),
    CheckConstraint("role IN ('admin','recruiter')"),
)
jobs = table("jobs", uid(), txt("title", nullable=False), txt("jd_text", nullable=False),
             txt("department"), txt("seniority"), txt("location"), txt("status", "draft", False),
             txt("recruitment_track", "general", False), tenant_id_column())
competencies = table("competencies", uid(), uid("job_id", "jobs.id"), txt("name", nullable=False),
                     txt("description", nullable=False), integer("weight_bp"), document("bars_anchors"),
                     integer("order_index"), txt("status", "proposed", False), tenant_id_column(),
                     UniqueConstraint("job_id", "name"), CheckConstraint("weight_bp BETWEEN 0 AND 10000"))
candidates = table("candidates", uid(), uid("job_id", "jobs.id", ondelete="RESTRICT"),
                   txt("full_name", nullable=False), txt("email"), txt("phone"), txt("source"),
                   date("retained_until", False), date("deleted_at"), date("erased_at"), tenant_id_column(),
                   CheckConstraint("erased_at IS NULL OR deleted_at IS NOT NULL"))
resumes = table("resumes", uid(), uid("candidate_id", "candidates.id"), txt("file_name", nullable=False),
                txt("mime_type", nullable=False), txt("raw_text", nullable=False), document("parsed"),
                document("unverified_claims"), tenant_id_column())
interviews = table("interviews", uid(), uid("candidate_id", "candidates.id", ondelete="RESTRICT"),
                   uid("job_id", "jobs.id", ondelete="RESTRICT"), txt("status", "created", False),
                   integer("duration_minutes"), txt("invite_token_hash"), date("invite_expires_at"),
                   txt("plan_version"), date("retained_until", False), txt("mode", "text", False),
                   txt("locale", "zh-CN", False), integer("version"), integer("current_question_seq"),
                   date("started_at"), date("finished_at"), date("last_activity_at"), date("paused_at"),
                   integer("paused_total_sec"), boolean("camera_required"), boolean("camera_active"),
                   boolean("microphone_active"), date("media_last_seen_at"), boolean("text_fallback"),
                   txt("recruitment_track", "general", False), document("graduate_verification", True),
                   integer("retention_days", 90), tenant_id_column(), UniqueConstraint("invite_token_hash"),
                   CheckConstraint("duration_minutes IN (15,30,45)"),
                   CheckConstraint("retention_days BETWEEN 1 AND 90"))
questions = table("questions", uid(), uid("interview_id", "interviews.id"),
                  uid("competency_id", "competencies.id", ondelete="RESTRICT"), integer("seq"),
                  txt("prompt", nullable=False), txt("intent"), document("followups"), integer("time_budget_sec", 1),
                  txt("status", "pending", False), txt("topic_key"), boolean("mandatory"),
                  txt("assessment_mode", "scored", False), tenant_id_column(), UniqueConstraint("interview_id", "seq"),
                  CheckConstraint("seq > 0 AND time_budget_sec > 0"))
turns = table("turns", uid(), uid("interview_id", "interviews.id"),
              uid("question_id", "questions.id", True, "SET NULL"), integer("seq"),
              txt("role", nullable=False), txt("content", nullable=False), boolean("is_followup"),
              uid("parent_turn_id", "turns.id", True, "SET NULL"), boolean("redacted"), tenant_id_column(),
              UniqueConstraint("interview_id", "seq", name="turns_interview_seq_uq"),
              UniqueConstraint("id", "interview_id"), CheckConstraint("seq > 0"))
evidence = table("evidence", uid(), uid("interview_id", "interviews.id"), uid("turn_id", "turns.id"),
                 uid("competency_id", "competencies.id", ondelete="RESTRICT"), txt("quote", nullable=False),
                 integer("start_offset", nullable=True), integer("end_offset", nullable=True), tenant_id_column(),
                 UniqueConstraint("id", "interview_id", "competency_id"),
                 ForeignKeyConstraint(["turn_id", "interview_id"], ["turns.id", "turns.interview_id"], ondelete="CASCADE"),
                 CheckConstraint("length(trim(quote)) > 0"))
scores = table("scores", uid(), uid("interview_id", "interviews.id"),
               uid("competency_id", "competencies.id", ondelete="RESTRICT"),
               uid("evidence_id", "evidence.id", True, "SET NULL"), txt("value", nullable=False),
               integer("numeric_value", nullable=True), boolean("needs_review"), txt("rationale"),
               integer("attempt", 1), txt("model"), txt("prompt_version"),
               integer("prompt_tokens", nullable=True), integer("completion_tokens", nullable=True),
               tenant_id_column(),
               UniqueConstraint("interview_id", "competency_id", "attempt"),
               ForeignKeyConstraint(["evidence_id", "interview_id", "competency_id"],
                                    ["evidence.id", "evidence.interview_id", "evidence.competency_id"]),
               CheckConstraint("(value = 'insufficient_evidence' AND evidence_id IS NULL AND numeric_value IS NULL) OR "
                               "(value IN ('1','2','3','4','5') AND evidence_id IS NOT NULL AND numeric_value BETWEEN 1 AND 5 AND CAST(numeric_value AS TEXT)=value)"),
               CheckConstraint("attempt IN (1,2)"))
score_revisions = table("score_revisions", uid(), uid("score_id", "scores.id"), txt("actor_id", nullable=False),
                        txt("actor_name"), txt("old_value", nullable=False), txt("new_value", nullable=False),
                        txt("reason", nullable=False), tenant_id_column())
reports = table("reports", uid(), uid("interview_id", "interviews.id"), txt("overall_summary", nullable=False),
                document("dimension_scores"), document("question_scores"), integer("revision", 1),
                document("highlights"), document("risks"), document("next_questions"),
                txt("recommendation", nullable=False), txt("recommendation_reason", nullable=False),
                document("metadata"), txt("prompt_version"), date("retained_until", False),
                Column("generated_at", UTCDateTime(), nullable=False, default=now), tenant_id_column(),
                UniqueConstraint("interview_id"))
consents = table("consents", uid(), uid("interview_id", "interviews.id"), txt("consent_version", nullable=False),
                 txt("consent_text_hash", nullable=False), boolean("recording_allowed"), date("consented_at", False),
                 date("revoked_at"), txt("ip_hash"), tenant_id_column(),
                 UniqueConstraint("interview_id", "consent_version"))
audit_logs = table("audit_logs", uid(), txt("actor_type", nullable=False), txt("actor_id"),
                   txt("action", nullable=False), txt("entity_type"), txt("entity_id"),
                   Column("interview_id", Uuid(as_uuid=False)), document("metadata", True), txt("ip_hash"),
                   tenant_id_column())
idempotency_keys = table("idempotency_keys", uid(), txt("scope", nullable=False), txt("key", nullable=False),
                         txt("request_hash", nullable=False), txt("status", "in_progress", False),
                         integer("response_status", nullable=True), document("response_body", True),
                         date("expires_at", False), Column("owner_candidate_id", Uuid(as_uuid=False)),
                         Column("owner_interview_id", Uuid(as_uuid=False)), tenant_id_column(),
                         UniqueConstraint("scope", "key"))
data_policies = table("data_policies", Column("id", String, primary_key=True), integer("retention_days", 90),
                      integer("revision", 1), txt("updated_by", "system", False), tenant_id_column(),
                      CheckConstraint("id = 'workspace' AND retention_days BETWEEN 1 AND 90 AND revision > 0"))
interview_events = table(
    "interview_events",
    uid(),
    uid("interview_id", "interviews.id"),
    integer("seq", 1),
    txt("event_type", nullable=False),
    document("payload"),
    Column("ts", UTCDateTime(), nullable=False, default=now),
    tenant_id_column(),
    UniqueConstraint("interview_id", "seq", name="interview_events_interview_seq_uq"),
    CheckConstraint("seq > 0"),
    CheckConstraint(
        "event_type IN ('state_changed','question_asked','answer_received','consent_granted',"
        "'interrupted','score_computed','report_generated')"
    ),
)
ai_usage = table(
    "ai_usage",
    uid(),
    Column("tenant", String(36), ForeignKey("tenants.id"), nullable=True, default=DEFAULT_TENANT_ID),
    txt("provider", nullable=False),
    txt("kind", nullable=False),
    Column("amount", Float, nullable=False),
    Column("ts", UTCDateTime(), nullable=False, default=now),
    CheckConstraint("kind IN ('llm_tokens','asr_seconds','tts_chars')"),
    CheckConstraint("amount >= 0"),
)
TABLES = {item.name: item for item in metadata.sorted_tables}
# The legacy recruitment snapshot format has a fixed table set. Practice stays local to this database.
practice_sessions = table("practice_sessions", uid(), txt("token_hash", nullable=False),
                          txt("consent_version", nullable=False), document("turns"),
                          date("retained_until", False), tenant_id_column(), UniqueConstraint("token_hash"))


def rows(connection: StorageSession | Connection, statement: Executable) -> list[Row]:
    return repository(connection).rows(statement)


def one(connection: StorageSession | Connection, entity: Table, identity: str) -> Row | None:
    result = rows(connection, select(entity).where(entity.c.id == identity))
    return result[0] if result else None


def insert(connection: StorageSession | Connection, entity: Table, values: Mapping[str, object]) -> Row:
    identity = values.get("id", identifier())
    values = {"id": identity, **values}
    # Stamp tenant from request context when the caller did not set one explicitly.
    if "tenant_id" in entity.c and values.get("tenant_id") is None:
        values["tenant_id"] = current_tenant()
    if entity.name == "ai_usage" and "tenant" in entity.c and values.get("tenant") is None:
        values["tenant"] = current_tenant()
    repository(connection).command(entity.insert().values(**values))
    result = one(connection, entity, str(identity))
    assert result is not None
    return result


def update(connection: StorageSession | Connection, entity: Table, identity: str, **values: object) -> None:
    repository(connection).command(entity.update().where(entity.c.id == identity).values(**values, updated_at=now()))


class Database:
    def __init__(self, settings: Settings) -> None:
        self.lock = threading.RLock()
        self.postgres = bool(settings.database_url)
        if self.postgres:
            url = settings.database_url.replace("postgres://", "postgresql+psycopg://", 1)
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+psycopg://", 1)
            self.engine = create_engine(url, pool_pre_ping=True, echo=False, hide_parameters=True)
        else:
            if settings.sqlite_path != ":memory:":
                Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine("sqlite://" if settings.sqlite_path == ":memory:" else
                                        f"sqlite:///{Path(settings.sqlite_path).as_posix()}",
                                        connect_args={"check_same_thread": False}, poolclass=StaticPool,
                                        echo=False, hide_parameters=True)
            event.listen(self.engine, "connect", self._sqlite_connect)

    @staticmethod
    def _sqlite_connect(connection: object, _record: object) -> None:
        import sqlite3
        assert isinstance(connection, sqlite3.Connection)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.lock, self.engine.begin() as connection:
            if self.postgres:
                connection.execute(text("SELECT pg_advisory_xact_lock(81720425)"))
                # RLS policies read app.tenant_id; SET LOCAL (is_local=true) for this transaction only.
                # Pool checkout reuse is safe: LOCAL ends with the transaction / connection return.
                connection.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": current_tenant()},
                )
            yield connection

    @contextmanager
    def unit_of_work(self) -> Iterator[StorageSession]:
        with self.transaction() as connection:
            yield SQLAlchemyRepository(connection)

    @contextmanager
    def historical_answer_import(self, connection: Connection) -> Iterator[None]:
        """Offline import only, inside the caller's exclusive atomic transaction."""
        if self.postgres:
            connection.exec_driver_sql("ALTER TABLE turns DISABLE TRIGGER candidate_answer_gate")
        else:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            connection.exec_driver_sql("DROP TRIGGER candidate_answer_gate")
        yield
        # On exceptions the surrounding transaction restores the prior trigger/schema.
        if self.postgres:
            connection.exec_driver_sql("ALTER TABLE turns ENABLE TRIGGER candidate_answer_gate")
        else:
            initial = (ROOT / "apps/api/migrations/sqlite/0001_initial.sql").read_text("utf-8")
            gate = next(part for part in initial.split("-- statement-breakpoint")
                        if "CREATE TRIGGER IF NOT EXISTS candidate_answer_gate " in part)
            connection.exec_driver_sql(gate)

    def migrate(self) -> None:
        if self.postgres:
            self._postgres_migrate()
        else:
            with self.engine.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE IF NOT EXISTS __python_migrations (id text PRIMARY KEY, checksum text NOT NULL, applied_at text NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            for file in sorted((ROOT / "apps/api/migrations/sqlite").glob("*.sql")):
                content = file.read_bytes().decode("utf-8-sig")
                checksum = hashlib.sha256(content.encode()).hexdigest()
                with self.engine.begin() as connection:
                    previous = connection.execute(text("SELECT checksum FROM __python_migrations WHERE id=:id"), {"id": file.name}).scalar()
                    if previous:
                        if previous != checksum:
                            raise RuntimeError(f"Applied migration checksum changed: {file.name}")
                        continue
                    for statement in content.split("-- statement-breakpoint"):
                        if statement.strip():
                            connection.exec_driver_sql(statement)
                    connection.execute(text("INSERT INTO __python_migrations(id,checksum) VALUES (:id,:checksum)"), {"id": file.name, "checksum": checksum})
        with self.transaction() as connection:
            # Ensure default tenant exists before any FK-backed seed rows (SQLite/PG).
            repository(connection).insert_if_absent(
                tenants,
                {"id": DEFAULT_TENANT_ID, "name": "default", "status": "active"},
                ["id"],
            )
            repository(connection).insert_if_absent(
                data_policies,
                {
                    "id": "workspace",
                    "retention_days": 90,
                    "revision": 1,
                    "tenant_id": DEFAULT_TENANT_ID,
                },
                ["id"],
            )

    def _postgres_migrate(self) -> None:
        with self.engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE IF NOT EXISTS __migrations (id text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
        for file in sorted((ROOT / "apps/api/migrations/postgres").glob("*.sql")):
            content = file.read_bytes().decode("utf-8-sig")
            checksum = hashlib.sha256(content.encode()).hexdigest()
            with self.engine.begin() as connection:
                previous = connection.execute(text("SELECT checksum FROM __migrations WHERE id=:id"), {"id": file.name}).scalar()
                if previous:
                    if previous != checksum:
                        raise RuntimeError(f"Applied migration checksum changed: {file.name}")
                    continue
                # Preserve PL/pgSQL percent literals and send multi-statement DDL without bind parameters.
                connection.exec_driver_sql(content, execution_options={"no_parameters": True})
                connection.execute(text("INSERT INTO __migrations(id,checksum) VALUES (:id,:checksum)"),
                                   {"id": file.name, "checksum": checksum})

    def close(self) -> None:
        self.engine.dispose()



def command(connection: StorageSession | Connection, statement: Executable) -> None:
    repository(connection).command(statement)


def scalar(connection: StorageSession | Connection, statement: Executable) -> object:
    return repository(connection).scalar(statement)


def exists(connection: StorageSession | Connection, statement: Executable) -> bool:
    return repository(connection).exists(statement)
