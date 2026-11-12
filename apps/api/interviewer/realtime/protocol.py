"""Bidirectional WS message protocol — single source of truth for Task 6b.

Generate TypeScript with:
  PYTHONPATH=apps/api python scripts/export_realtime_protocol_ts.py
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

PROTOCOL_VERSION = "aii-ws-v1"

# D75: keep base64 JSON frames; 1s of PCM16LE @ 16kHz mono = 32000 bytes.
MAX_AUDIO_CHUNK_PCM_BYTES = 32_000
MAX_AUDIO_CHUNK_BASE64_CHARS = 44_000

ClientType = Literal[
    "auth", "start", "audio_chunk", "text_input", "end_turn", "interrupt",
    "proctor_signal", "ping", "close",
]
ServerType = Literal[
    "ready", "question", "partial_transcript", "final_transcript", "tts_chunk",
    "interrupted", "error", "pong", "state_changed", "event_replay",
]


class Envelope(BaseModel):
    v: Literal["aii-ws-v1"] = "aii-ws-v1"
    type: str


class AuthMessage(Envelope):
    type: Literal["auth"] = "auth"
    token: str = Field(min_length=8, max_length=512)
    resume_from_seq: int = Field(default=0, ge=0, alias="resumeFromSeq")

    model_config = {"populate_by_name": True}


class StartMessage(Envelope):
    type: Literal["start"] = "start"


class AudioChunkMessage(Envelope):
    """PCM16LE 16kHz mono fragment as base64 (D75 — no binary frames yet)."""

    type: Literal["audio_chunk"] = "audio_chunk"
    seq: int = Field(ge=0)
    pcm_base64: str | None = Field(
        default=None,
        alias="pcmBase64",
        max_length=MAX_AUDIO_CHUNK_BASE64_CHARS,
    )
    format: Literal["pcm16le_16k"] = "pcm16le_16k"

    model_config = {"populate_by_name": True}


class TextInputMessage(Envelope):
    type: Literal["text_input"] = "text_input"
    text: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=8, max_length=200, alias="idempotencyKey")
    expected_question_seq: int | None = Field(default=None, ge=1, alias="expectedQuestionSeq")

    model_config = {"populate_by_name": True}


class EndTurnMessage(Envelope):
    type: Literal["end_turn"] = "end_turn"
    idempotency_key: str | None = Field(default=None, max_length=200, alias="idempotencyKey")

    model_config = {"populate_by_name": True}


class InterruptMessage(Envelope):
    type: Literal["interrupt"] = "interrupt"


class ProctorSignalMessage(Envelope):
    """Client telemetry for Task 7 — never treated as assessment content."""

    type: Literal["proctor_signal"] = "proctor_signal"
    signal_type: Literal[
        "tab_hidden", "window_blur", "answer_latency",
        "silence_ratio", "volume_spike", "speech_rate",
    ] = Field(alias="signalType")
    payload: dict[str, object] = Field(default_factory=dict)
    t: int | None = None

    model_config = {"populate_by_name": True}


class PingMessage(Envelope):
    type: Literal["ping"] = "ping"
    t: int | None = None


class CloseMessage(Envelope):
    type: Literal["close"] = "close"
    reason: str | None = Field(default=None, max_length=200)


ClientMessage = Annotated[
    AuthMessage | StartMessage | AudioChunkMessage | TextInputMessage
    | EndTurnMessage | InterruptMessage | ProctorSignalMessage | PingMessage | CloseMessage,
    Field(discriminator="type"),
]


class ReadyMessage(Envelope):
    type: Literal["ready"] = "ready"
    interview_id: str = Field(alias="interviewId")
    tenant_bound: bool = Field(default=True, alias="tenantBound")
    status: str
    resume_from_seq: int = Field(alias="resumeFromSeq")
    protocol_version: str = Field(default=PROTOCOL_VERSION, alias="protocolVersion")

    model_config = {"populate_by_name": True}


class QuestionMessage(Envelope):
    type: Literal["question"] = "question"
    question_seq: int = Field(alias="questionSeq", ge=1)
    text: str
    intent: str | None = None

    model_config = {"populate_by_name": True}


class PartialTranscriptMessage(Envelope):
    type: Literal["partial_transcript"] = "partial_transcript"
    text: str


class FinalTranscriptMessage(Envelope):
    type: Literal["final_transcript"] = "final_transcript"
    text: str


class TtsChunkMessage(Envelope):
    type: Literal["tts_chunk"] = "tts_chunk"
    seq: int = Field(ge=0)
    audio_base64: str | None = Field(default=None, alias="audioBase64")

    model_config = {"populate_by_name": True}


class InterruptedMessage(Envelope):
    type: Literal["interrupted"] = "interrupted"
    at: str | None = None
    reason: Literal["vad_barge_in", "client", "device_lost"] | None = None


class ErrorMessage(Envelope):
    type: Literal["error"] = "error"
    code: str
    message: str


class PongMessage(Envelope):
    type: Literal["pong"] = "pong"
    t: int | None = None


class StateChangedMessage(Envelope):
    type: Literal["state_changed"] = "state_changed"
    status: str
    detail: dict[str, object] = Field(default_factory=dict)


class EventReplayMessage(Envelope):
    type: Literal["event_replay"] = "event_replay"
    from_seq: int = Field(alias="fromSeq", ge=0)
    events: list[dict[str, object]]

    model_config = {"populate_by_name": True}


ServerMessage = Annotated[
    ReadyMessage | QuestionMessage | PartialTranscriptMessage | FinalTranscriptMessage
    | TtsChunkMessage | InterruptedMessage | ErrorMessage | PongMessage
    | StateChangedMessage | EventReplayMessage,
    Field(discriminator="type"),
]

_client_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)  # type: ignore[arg-type,unused-ignore]
_server_adapter: TypeAdapter[ServerMessage] = TypeAdapter(ServerMessage)  # type: ignore[arg-type,unused-ignore]


def parse_client_message(raw: object) -> ClientMessage:
    return _client_adapter.validate_python(raw)


def parse_client_json(text: str) -> ClientMessage:
    return _client_adapter.validate_json(text)


def dump_server_message(message: ServerMessage) -> str:
    return message.model_dump_json(by_alias=True, exclude_none=True)


def client_validation_error(text: str) -> str | None:
    try:
        parse_client_json(text)
        return None
    except ValidationError as error:
        return str(error)


CLIENT_TYPES: tuple[str, ...] = (
    "auth", "start", "audio_chunk", "text_input", "end_turn", "interrupt",
    "proctor_signal", "ping", "close",
)
SERVER_TYPES: tuple[str, ...] = (
    "ready", "question", "partial_transcript", "final_transcript", "tts_chunk",
    "interrupted", "error", "pong", "state_changed", "event_replay",
)
