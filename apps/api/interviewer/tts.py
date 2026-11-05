"""Opt-in Edge TTS. Only authenticated, server-owned current questions leave the server."""
from __future__ import annotations

import asyncio
import importlib
import threading
from collections.abc import AsyncIterator, Callable
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Protocol, cast

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from .domain import FOLLOWUP_TEXT
from .errors import DomainError
from .safety import redact, safe_question
from .settings import Settings

if TYPE_CHECKING:
    from .service import Service

MAX_TTS_BYTES = 2 * 1024 * 1024
EDGE_VERSION = "7.3.1"


class Communicate(Protocol):
    def stream(self) -> AsyncIterator[object]: ...


class EdgeModule(Protocol):
    def Communicate(self, text: str, voice: str, *, rate: str, connect_timeout: int,
                    receive_timeout: int) -> Communicate: ...


class AudioChunk(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    type: str
    data: bytes = Field(max_length=MAX_TTS_BYTES)


Factory = Callable[[str, Settings], Communicate]


class EdgeTTS:
    def __init__(self, settings: Settings, factory: Factory | None = None) -> None:
        self.settings, self._factory = settings, factory
        self._slots = threading.BoundedSemaphore(settings.tts_max_concurrency)

    def prepare(self) -> None:
        if self.settings.tts_provider != "edge" or not self.settings.tts_allow_external or not self.settings.tts_voice:
            raise DomainError("SPEECH_UNAVAILABLE", "Edge TTS需要明确允许外网和配置音色，不会静默启用")
        if self._factory is not None:
            return
        try:
            if version("edge-tts") != EDGE_VERSION:
                raise DomainError("SPEECH_UNAVAILABLE", "请使用requirements-edge.txt锁定的Edge TTS版本")
            module = cast(EdgeModule, importlib.import_module("edge_tts"))
        except (ImportError, PackageNotFoundError):
            raise DomainError("SPEECH_UNAVAILABLE", "缺少可选Edge TTS依赖，请使用离线依赖包准备环境") from None

        def factory(text: str, settings: Settings) -> Communicate:
            return module.Communicate(text, settings.tts_voice, rate=settings.tts_rate,
                                      connect_timeout=settings.tts_connect_timeout, receive_timeout=settings.tts_timeout)
        self._factory = factory

    async def synthesize(self, text: str) -> bytes:
        self.prepare()
        if not text.strip() or len(text) > 1000:
            raise DomainError("SPEECH_UNAVAILABLE", "题目超出播报长度限制，请阅读题目文字")
        if not self._slots.acquire(blocking=False):
            raise DomainError("SPEECH_UNAVAILABLE", "题目播报繁忙，请稍后重试")
        try:
            assert self._factory is not None
            async with asyncio.timeout(self.settings.tts_timeout):
                output = bytearray()
                async for raw in self._factory(text, self.settings).stream():
                    if not isinstance(raw, dict) or raw.get("type") != "audio":
                        continue
                    chunk = AudioChunk.model_validate(raw)
                    output.extend(chunk.data)
                    if len(output) > MAX_TTS_BYTES:
                        raise ValueError("Audio response too large")
                if not output:
                    raise ValueError("No audio received")
                return bytes(output)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise DomainError("SPEECH_UNAVAILABLE", "Edge题目播报失败或超时，请阅读题目文字；没有切换其他云服务") from None
        finally:
            self._slots.release()


def current_question(service: Service, request: Request, identity: str, question_seq: int, turn_seq: int,
                     audio_bytes: int | None = None) -> str:
    from .speech import check_speech
    check_speech(service, request, identity)
    with service.database.unit_of_work() as connection:
        row = service.interview(connection, identity, True)
        if not service.current_consent(connection, row):
            raise DomainError("CONSENT_REQUIRED", "播报处理方式已变化，请重新阅读当前同意文本并开始新面试")
        state = service.state(connection, identity)
        question = next((item for item in service.question_rows(connection, identity) if item["seq"] == question_seq), None)
        spoken = next((item for item in reversed(service.turn_rows(connection, identity)) if item["role"] == "interviewer"), None)
        if state["questionSeq"] != question_seq or not question or not spoken or spoken["seq"] != turn_seq or spoken["question_id"] != question["id"]:
            raise DomainError("RESOURCE_CONFLICT", "题目已变化，请刷新后播报当前题目")
        text = str(spoken["content"])
        # Existing plans and followups are fixed server templates; candidate text is never accepted.
        if text not in {str(question["prompt"]), *FOLLOWUP_TEXT.values()} or redact(text) != text:
            raise DomainError("SPEECH_UNAVAILABLE", "当前题目不适合外网播报，请阅读题目文字")
        safe_question(text)
        if audio_bytes is not None:
            service.audit(connection, "speech.synthesized", identity,
                          {"vendor": "edge", "bytes": audio_bytes, "audioStored": False, "candidateContentSent": False}, interview_id=identity)
        return text
