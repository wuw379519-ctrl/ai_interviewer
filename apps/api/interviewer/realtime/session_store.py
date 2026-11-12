"""In-process WS session registry — one active writer per interview (D74)."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import WebSocket

from interviewer import events
from interviewer.contracts import Object
from interviewer.tenancy import reset_current_tenant, set_current_tenant

if TYPE_CHECKING:
    from interviewer.service import Service

CLOSE_SUPERSEDED = 4000


@dataclass
class LiveSession:
    interview_id: str
    tenant_id: str
    connection_id: str
    websocket: WebSocket
    created_at: float = field(default_factory=time.monotonic)
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionStore:
    """Exclusive writer WS per interview_id; reconnect kicks the previous socket."""

    def __init__(self) -> None:
        self._sessions: dict[str, LiveSession] = {}
        self._guard = asyncio.Lock()

    async def attach(
        self,
        interview_id: str,
        tenant_id: str,
        websocket: WebSocket,
    ) -> LiveSession:
        connection_id = str(uuid4())
        session = LiveSession(
            interview_id=interview_id,
            tenant_id=tenant_id,
            connection_id=connection_id,
            websocket=websocket,
        )
        async with self._guard:
            previous = self._sessions.get(interview_id)
            self._sessions[interview_id] = session
        if previous is not None and previous.connection_id != connection_id:
            try:
                await previous.websocket.close(code=CLOSE_SUPERSEDED, reason="superseded")
            except Exception:
                pass
        return session

    async def detach(self, interview_id: str, connection_id: str) -> None:
        async with self._guard:
            current = self._sessions.get(interview_id)
            if current and current.connection_id == connection_id:
                del self._sessions[interview_id]

    def get(self, interview_id: str) -> LiveSession | None:
        return self._sessions.get(interview_id)

    def events_after(self, service: Service, interview_id: str, tenant_id: str, after_seq: int) -> list[Object]:
        """Replay interview_events with seq > after_seq under the interview tenant."""
        token = set_current_tenant(tenant_id)
        try:
            with service.database.unit_of_work() as connection:
                rows = events.list_events(connection, interview_id)
            return [row for row in rows if int(str(row["seq"])) > after_seq]
        finally:
            reset_current_tenant(token)

    def latest_seq(self, service: Service, interview_id: str, tenant_id: str) -> int:
        token = set_current_tenant(tenant_id)
        try:
            with service.database.unit_of_work() as connection:
                rows = events.list_events(connection, interview_id)
            return max((int(str(row["seq"])) for row in rows), default=0)
        finally:
            reset_current_tenant(token)
