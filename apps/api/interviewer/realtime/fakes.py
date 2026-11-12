"""Injectable fake ASR/TTS for Task 6b tests and latency measurement (no network)."""
from __future__ import annotations

import asyncio
import time

from interviewer.contracts import SpeechOutput


class FakeASR:
    name = "fake_asr"

    def __init__(self, text: str = "我主导了模块实现，将处理耗时降低30%。", delay_ms: float = 5.0) -> None:
        self.text = text
        self.delay_ms = delay_ms
        self.calls = 0

    def transcribe(self, content: bytes) -> SpeechOutput:
        self.calls += 1
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000.0)
        _ = content
        return SpeechOutput(text=self.text)

    def load(self) -> object:
        return self

    def close(self) -> None:
        return None


class FakeTTS:
    name = "fake_tts"

    def __init__(self, delay_ms: float = 5.0, payload: bytes | None = None) -> None:
        self.delay_ms = delay_ms
        self.payload = payload or (b"\x00\x01" * 640)  # ~20 ms PCM-ish
        self.calls = 0

    def prepare(self) -> None:
        return None

    async def synthesize(self, text: str) -> bytes:
        self.calls += 1
        _ = text
        if self.delay_ms > 0:
            await asyncio.sleep(self.delay_ms / 1000.0)
        return self.payload
