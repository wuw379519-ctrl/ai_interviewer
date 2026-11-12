"""Realtime WebSocket gateway — protocol, session store, pipeline (Task 6b)."""
from __future__ import annotations

from .protocol import PROTOCOL_VERSION, parse_client_message
from .session_store import SessionStore
from .ws_router import build_realtime_router

__all__ = [
    "PROTOCOL_VERSION",
    "SessionStore",
    "build_realtime_router",
    "parse_client_message",
]
