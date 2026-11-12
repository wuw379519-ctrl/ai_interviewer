"""Realtime WebSocket gateway skeleton (Task 6a). Full audio pipeline is Task 7b."""
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
