"""Task 6a: Pydantic validation for WS protocol messages."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from interviewer.realtime.protocol import (
    PROTOCOL_VERSION,
    parse_client_json,
    parse_client_message,
    ReadyMessage,
    dump_server_message,
)


def test_auth_and_ping_round_trip() -> None:
    auth = parse_client_json(
        '{"v":"aii-ws-v1","type":"auth","token":"invite-token-value","resumeFromSeq":3}'
    )
    assert auth.type == "auth"
    assert auth.token == "invite-token-value"
    assert auth.resume_from_seq == 3
    ping = parse_client_message({"v": PROTOCOL_VERSION, "type": "ping", "t": 1})
    assert ping.type == "ping"


def test_rejects_unknown_type_and_empty_text() -> None:
    with pytest.raises(ValidationError):
        parse_client_json('{"v":"aii-ws-v1","type":"nope"}')
    with pytest.raises(ValidationError):
        parse_client_json('{"v":"aii-ws-v1","type":"text_input","text":""}')
    with pytest.raises(ValidationError):
        parse_client_json(
            '{"v":"aii-ws-v1","type":"text_input","text":"hi","idempotencyKey":"short"}'
        )


def test_text_input_requires_idempotency_key() -> None:
    msg = parse_client_json(
        '{"v":"aii-ws-v1","type":"text_input","text":"回答内容",'
        '"idempotencyKey":"ws-key-abcdefgh"}'
    )
    assert msg.type == "text_input"
    assert msg.idempotency_key == "ws-key-abcdefgh"


def test_server_ready_dumps_aliases() -> None:
    raw = dump_server_message(
        ReadyMessage(interviewId="00000000-0000-4000-8000-000000000099", status="interviewing", resumeFromSeq=2)
    )
    assert "interviewId" in raw and "resumeFromSeq" in raw
