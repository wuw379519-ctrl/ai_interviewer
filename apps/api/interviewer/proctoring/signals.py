"""Append / list proctor_logs under the current tenant (Task 7 / 9b)."""
from __future__ import annotations

from typing import Literal

from sqlalchemy import select

from interviewer import database as db
from interviewer.contracts import Object
from interviewer.repository import StorageSession
from interviewer.safety import sanitize_metadata
from interviewer.tenancy import current_tenant

SIGNAL_TYPES = frozenset({
    "tab_hidden",
    "window_blur",
    "answer_latency",
    "silence_ratio",
    "volume_spike",
    "speech_rate",
    "no_face",
    "multi_face",
    "camera_stall",
    "camera_lost",
})

SignalType = Literal[
    "tab_hidden", "window_blur", "answer_latency",
    "silence_ratio", "volume_spike", "speech_rate",
    "no_face", "multi_face", "camera_stall", "camera_lost",
]


def append_proctor_log(
    connection: StorageSession,
    interview_id: str,
    signal_type: str,
    payload: Object | None = None,
) -> db.Row:
    if signal_type not in SIGNAL_TYPES:
        raise ValueError(f"unsupported signal_type: {signal_type}")
    clean = sanitize_metadata(payload or {})
    return db.insert(
        connection,
        db.proctor_logs,
        {
            "interview_id": interview_id,
            "signal_type": signal_type,
            "payload": clean,
            "tenant_id": current_tenant(),
            "ts": db.now(),
        },
    )


def list_proctor_logs(connection: StorageSession, interview_id: str) -> list[Object]:
    rows = db.rows(
        connection,
        select(db.proctor_logs)
        .where(
            db.proctor_logs.c.interview_id == interview_id,
            db.proctor_logs.c.tenant_id == current_tenant(),
        )
        .order_by(db.proctor_logs.c.ts.asc()),
    )
    return [
        {
            "id": str(row["id"]),
            "interviewId": str(row["interview_id"]),
            "signalType": str(row["signal_type"]),
            "payload": dict(row["payload"]) if isinstance(row["payload"], dict) else {},
            "ts": db.iso(row["ts"]),
            "tenantId": str(row["tenant_id"]),
        }
        for row in rows
    ]
