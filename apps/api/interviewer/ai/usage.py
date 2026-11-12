"""Persist ai_usage meter rows (tenant nullable until Task 4)."""
from __future__ import annotations

from typing import Literal

from interviewer import database as db
from interviewer.repository import StorageSession

UsageKind = Literal["llm_tokens", "asr_seconds", "tts_chars"]


def record_ai_usage(
    connection: StorageSession,
    *,
    provider: str,
    kind: UsageKind,
    amount: float,
    tenant: str | None = None,
) -> db.Row:
    return db.insert(
        connection,
        db.ai_usage,
        {
            "tenant": tenant,
            "provider": provider,
            "kind": kind,
            "amount": float(amount),
            "ts": db.now(),
        },
    )
