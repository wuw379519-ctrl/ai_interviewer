"""Canonical business-schema inventory shared by SQLite and Postgres parity checks."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.engine import Connection, Engine
from sqlalchemy import inspect, text


# Tables required after the full migration chain on either driver.
BUSINESS_TABLES: frozenset[str] = frozenset({
    "audit_logs",
    "candidates",
    "competencies",
    "consents",
    "data_policies",
    "evidence",
    "idempotency_keys",
    "interview_events",
    "interviews",
    "jobs",
    "practice_sessions",
    "questions",
    "reports",
    "resumes",
    "score_revisions",
    "scores",
    "turns",
})

# Key columns that must exist with matching nullability on both drivers.
REQUIRED_COLUMNS: Mapping[str, Mapping[str, bool]] = {
    "jobs": {
        "id": False, "title": False, "jd_text": False, "department": True, "seniority": True,
        "location": True, "status": False, "recruitment_track": False, "created_at": False, "updated_at": False,
    },
    "candidates": {
        "id": False, "job_id": False, "full_name": False, "email": True, "phone": True, "source": True,
        "retained_until": False, "deleted_at": True, "erased_at": True, "created_at": False, "updated_at": False,
    },
    "competencies": {
        "id": False, "job_id": False, "name": False, "description": False, "weight_bp": False,
        "bars_anchors": False, "order_index": False, "status": False, "created_at": False, "updated_at": False,
    },
    "interviews": {
        "id": False, "candidate_id": False, "job_id": False, "status": False, "duration_minutes": False,
        "invite_token_hash": True, "invite_expires_at": True, "plan_version": True, "retained_until": False,
        "mode": False, "locale": False, "version": False, "current_question_seq": False, "started_at": True,
        "finished_at": True, "last_activity_at": True, "paused_at": True, "paused_total_sec": False,
        "camera_required": False, "camera_active": False, "microphone_active": False, "media_last_seen_at": True,
        "text_fallback": False, "recruitment_track": False, "graduate_verification": True, "retention_days": False,
        "created_at": False, "updated_at": False,
    },
    "questions": {
        "id": False, "interview_id": False, "competency_id": False, "seq": False, "prompt": False,
        "intent": True, "followups": False, "time_budget_sec": False, "status": False, "topic_key": True,
        "mandatory": False, "assessment_mode": False, "created_at": False, "updated_at": False,
    },
    "turns": {
        "id": False, "interview_id": False, "question_id": True, "seq": False, "role": False, "content": False,
        "is_followup": False, "parent_turn_id": True, "redacted": False, "created_at": False, "updated_at": False,
    },
    "evidence": {
        "id": False, "interview_id": False, "turn_id": False, "competency_id": False, "quote": False,
        "start_offset": True, "end_offset": True, "created_at": False, "updated_at": False,
    },
    "scores": {
        "id": False, "interview_id": False, "competency_id": False, "evidence_id": True, "value": False,
        "numeric_value": True, "needs_review": False, "rationale": True, "attempt": False, "model": True,
        "prompt_version": True, "prompt_tokens": True, "completion_tokens": True, "created_at": False,
        "updated_at": False,
    },
    "score_revisions": {
        "id": False, "score_id": False, "actor_id": False, "actor_name": True, "old_value": False,
        "new_value": False, "reason": False, "created_at": False, "updated_at": False,
    },
    "reports": {
        "id": False, "interview_id": False, "overall_summary": False, "dimension_scores": False,
        "question_scores": False, "revision": False, "highlights": False, "risks": False,
        "next_questions": False, "recommendation": False, "recommendation_reason": False, "metadata": False,
        "prompt_version": True, "retained_until": False, "generated_at": False, "created_at": False,
        "updated_at": False,
    },
    "consents": {
        "id": False, "interview_id": False, "consent_version": False, "consent_text_hash": False,
        "recording_allowed": False, "consented_at": False, "revoked_at": True, "ip_hash": True,
        "created_at": False, "updated_at": False,
    },
    "resumes": {
        "id": False, "candidate_id": False, "file_name": False, "mime_type": False, "raw_text": False,
        "parsed": False, "unverified_claims": False, "created_at": False, "updated_at": False,
    },
    "idempotency_keys": {
        "id": False, "scope": False, "key": False, "request_hash": False, "status": False,
        "response_status": True, "response_body": True, "expires_at": False, "owner_candidate_id": True,
        "owner_interview_id": True, "created_at": False, "updated_at": False,
    },
    "data_policies": {
        "id": False, "retention_days": False, "revision": False, "updated_by": False,
        "created_at": False, "updated_at": False,
    },
    "audit_logs": {
        "id": False, "actor_type": False, "actor_id": True, "action": False, "entity_type": True,
        "entity_id": True, "interview_id": True, "metadata": True, "ip_hash": True,
        "created_at": False, "updated_at": False,
    },
    "practice_sessions": {
        "id": False, "token_hash": False, "consent_version": False, "turns": False,
        "retained_until": False, "created_at": False, "updated_at": False,
    },
    "interview_events": {
        "id": False, "interview_id": False, "seq": False, "event_type": False, "payload": False,
        "ts": False, "created_at": False, "updated_at": False,
    },
}

# Index names expected on both drivers after full migrate (unique table constraints may substitute).
REQUIRED_INDEXES: Mapping[str, frozenset[str]] = {
    "audit_logs": frozenset({"audit_logs_action_idx", "audit_logs_interview_idx", "audit_logs_created_at_idx"}),
    "candidates": frozenset({
        "candidates_job_idx", "candidates_email_idx", "candidates_deleted_at_idx",
        "candidates_retained_until_idx", "candidates_erased_at_idx",
    }),
    "competencies": frozenset({"competencies_job_idx"}),
    "consents": frozenset({"consents_interview_idx"}),
    "evidence": frozenset({"evidence_interview_idx", "evidence_turn_idx"}),
    "idempotency_keys": frozenset({
        "idempotency_expires_idx", "idempotency_candidate_idx", "idempotency_interview_idx",
    }),
    "interviews": frozenset({"interviews_candidate_idx", "interviews_status_idx"}),
    "jobs": frozenset({"jobs_status_idx", "jobs_created_at_idx"}),
    "questions": frozenset({"questions_interview_idx"}),
    "resumes": frozenset({"resumes_candidate_idx"}),
    "score_revisions": frozenset({"score_revisions_score_idx"}),
    "scores": frozenset({"scores_interview_idx", "scores_evidence_idx"}),
    "turns": frozenset({"turns_interview_idx", "turns_question_idx"}),
    "interview_events": frozenset({"interview_events_interview_idx"}),
}

# Safety gates that must exist (trigger name contains / equals these tokens).
REQUIRED_GATE_TOKENS: frozenset[str] = frozenset({
    "candidate_answer_gate",
    "evidence_quote_gate",
})

# Named integrity constraints / trigger abort codes that both drivers must enforce.
REQUIRED_CONSTRAINT_TOKENS: frozenset[str] = frozenset({
    "insufficient_evidence",
    "jobs_status_valid",
    "interviews_status_valid",
    "turns_role_valid",
    "reports_recommendation_valid",
    "questions_assessment_mode_valid",
    "interviews_recruitment_track_valid",
    "candidates_erased_requires_deleted",
})


@dataclass(frozen=True)
class SchemaSnapshot:
    tables: frozenset[str]
    columns: Mapping[str, Mapping[str, bool]]
    indexes: Mapping[str, frozenset[str]]
    gate_tokens: frozenset[str]
    constraint_tokens: frozenset[str]


def _sqlite_snapshot(connection: Connection) -> SchemaSnapshot:
    inspector = inspect(connection)
    tables = frozenset(name for name in inspector.get_table_names() if not name.startswith("__"))
    columns: dict[str, dict[str, bool]] = {}
    indexes: dict[str, set[str]] = {}
    for table in tables:
        columns[table] = {col["name"]: bool(col["nullable"]) for col in inspector.get_columns(table)}
        indexes[table] = {str(item["name"]) for item in inspector.get_indexes(table) if item.get("name")}
    trigger_sql = " ".join(
        str(row[0] or "")
        for row in connection.execute(text("SELECT sql FROM sqlite_master WHERE type IN ('trigger','table')")).fetchall()
    ).lower()
    gates = frozenset(token for token in REQUIRED_GATE_TOKENS if token in trigger_sql)
    constraints = frozenset(token for token in REQUIRED_CONSTRAINT_TOKENS if token.lower() in trigger_sql)
    # Table-level CHECK for erasure is named only in Postgres; SQLite embeds the predicate.
    if "erased_at is null or deleted_at is not null" in trigger_sql:
        constraints = constraints | frozenset({"candidates_erased_requires_deleted"})
    return SchemaSnapshot(
        tables=tables,
        columns=columns,
        indexes={name: frozenset(values) for name, values in indexes.items()},
        gate_tokens=gates,
        constraint_tokens=constraints,
    )


def _postgres_snapshot(connection: Connection) -> SchemaSnapshot:
    inspector = inspect(connection)
    tables = frozenset(name for name in inspector.get_table_names() if not name.startswith("__"))
    columns: dict[str, dict[str, bool]] = {}
    indexes: dict[str, set[str]] = {}
    for table in tables:
        columns[table] = {col["name"]: bool(col["nullable"]) for col in inspector.get_columns(table)}
        indexes[table] = {str(item["name"]) for item in inspector.get_indexes(table) if item.get("name")}
    trigger_names = {
        str(row[0])
        for row in connection.execute(text(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"
        )).fetchall()
    }
    check_rows = connection.execute(text(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE contype = 'c'"
    )).fetchall()
    check_blob = " ".join(f"{row[0]} {row[1]}" for row in check_rows).lower()
    catalog = " ".join(sorted(trigger_names)).lower()
    # Function bodies carry the evidence-quote / consent gate semantics.
    function_sql = " ".join(
        str(row[0] or "")
        for row in connection.execute(text(
            "SELECT pg_get_functiondef(oid) FROM pg_proc WHERE proname LIKE 'aii_guard_%'"
        )).fetchall()
    ).lower()
    blob = f"{catalog} {check_blob} {function_sql}"
    gates = frozenset(token for token in REQUIRED_GATE_TOKENS if token in blob)
    constraints = frozenset(token for token in REQUIRED_CONSTRAINT_TOKENS if token.lower() in blob)
    return SchemaSnapshot(
        tables=tables,
        columns=columns,
        indexes={name: frozenset(values) for name, values in indexes.items()},
        gate_tokens=gates,
        constraint_tokens=constraints,
    )


def collect_schema(engine: Engine, *, postgres: bool) -> SchemaSnapshot:
    with engine.connect() as connection:
        return _postgres_snapshot(connection) if postgres else _sqlite_snapshot(connection)


def assert_matches_canonical(snapshot: SchemaSnapshot) -> list[str]:
    """Return human-readable mismatches against the shared inventory."""
    problems: list[str] = []
    missing_tables = BUSINESS_TABLES - snapshot.tables
    if missing_tables:
        problems.append(f"missing tables: {sorted(missing_tables)}")
    for table, expected_cols in REQUIRED_COLUMNS.items():
        actual = snapshot.columns.get(table, {})
        for name, nullable in expected_cols.items():
            if name not in actual:
                problems.append(f"{table}.{name} missing")
            elif actual[name] != nullable:
                problems.append(f"{table}.{name} nullability want={nullable} got={actual[name]}")
    for table, expected_indexes in REQUIRED_INDEXES.items():
        actual_indexes = snapshot.indexes.get(table, frozenset())
        missing = expected_indexes - actual_indexes
        if missing:
            problems.append(f"{table} missing indexes: {sorted(missing)}")
    missing_gates = REQUIRED_GATE_TOKENS - snapshot.gate_tokens
    if missing_gates:
        problems.append(f"missing safety gates: {sorted(missing_gates)}")
    missing_constraints = REQUIRED_CONSTRAINT_TOKENS - snapshot.constraint_tokens
    if missing_constraints:
        problems.append(f"missing integrity tokens: {sorted(missing_constraints)}")
    return problems
