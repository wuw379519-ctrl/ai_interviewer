"""Interview event-sourcing helpers: append-only log within the caller's transaction."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from sqlalchemy import func, select

from . import database as db
from .contracts import Object
from .repository import StorageSession
from .tenancy import current_tenant

EventType = Literal[
    "state_changed",
    "question_asked",
    "answer_received",
    "consent_granted",
    "interrupted",
    "score_computed",
    "report_generated",
]

EVENT_TYPES: frozenset[str] = frozenset({
    "state_changed", "question_asked", "answer_received", "consent_granted",
    "interrupted", "score_computed", "report_generated",
})


def next_seq(connection: StorageSession, interview_id: str) -> int:
    current = db.scalar(
        connection,
        select(func.coalesce(func.max(db.interview_events.c.seq), 0)).where(
            db.interview_events.c.interview_id == interview_id,
            db.interview_events.c.tenant_id == current_tenant(),
        ),
    )
    return int(str(current or 0)) + 1


def append_event(
    connection: StorageSession,
    interview_id: str,
    event_type: EventType,
    payload: Mapping[str, object] | None = None,
) -> db.Row:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported event_type: {event_type}")
    seq = next_seq(connection, interview_id)
    return db.insert(
        connection,
        db.interview_events,
        {
            "interview_id": interview_id,
            "seq": seq,
            "event_type": event_type,
            "payload": dict(payload or {}),
            "ts": db.now(),
        },
    )


def list_events(connection: StorageSession, interview_id: str) -> list[Object]:
    rows = db.rows(
        connection,
        select(db.interview_events)
        .where(
            db.interview_events.c.interview_id == interview_id,
            db.interview_events.c.tenant_id == current_tenant(),
        )
        .order_by(db.interview_events.c.seq.asc()),
    )
    return [
        {
            "id": str(row["id"]),
            "interviewId": str(row["interview_id"]),
            "seq": int(str(row["seq"])),
            "eventType": str(row["event_type"]),
            "payload": row["payload"] if isinstance(row["payload"], dict) else {},
            "ts": db.iso(row["ts"]),
        }
        for row in rows
    ]
