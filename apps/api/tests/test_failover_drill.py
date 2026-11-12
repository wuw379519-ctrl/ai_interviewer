"""Task 8a failover drill: LLM/ASR/TTS primary failure → degrade, never stall."""
from __future__ import annotations

import asyncio

import pytest

from interviewer.ai.circuit import CircuitBreaker
from interviewer.ai.gateway import AIGateway, NullASR, NullTTS
from interviewer.contracts import SpeechOutput
from interviewer.errors import DomainError
from interviewer.settings import Settings


class CountingLLM:
    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.name = name
        self.model = "fake-model"
        self.fail = fail
        self.calls = 0
        self.reply = "unused"

    def usage(self, prompt: int, completion: int) -> dict[str, object]:
        return {"promptTokens": prompt, "completionTokens": completion}


class BoomASR:
    name = "boom_asr"

    def transcribe(self, _content: bytes) -> SpeechOutput:
        raise DomainError("SPEECH_UNAVAILABLE", "asr down")

    def load(self) -> object:
        return self

    def close(self) -> None:
        return None


class BoomTTS:
    name = "boom_tts"

    def prepare(self) -> None:
        return None

    async def synthesize(self, _text: str) -> bytes:
        raise DomainError("SPEECH_UNAVAILABLE", "tts down")


def _gateway(primary: CountingLLM, *, threshold: int = 3) -> AIGateway:
    return AIGateway(
        Settings(provider="fake", secret="fixture-" * 8),
        primary,  # type: ignore[arg-type]
        NullASR(),
        NullTTS(),
        llm_circuit=CircuitBreaker(failure_threshold=threshold, cooldown_sec=60.0),
    )


def test_llm_primary_error_uses_rule_next_question() -> None:
    primary = CountingLLM("broken", fail=True)
    gateway = _gateway(primary)

    def boom() -> str:
        primary.calls += 1
        raise DomainError("LLM_PROVIDER_UNAVAILABLE", "provider down")

    text, source = gateway.decide_next_question({1: "A", 2: "B-fallback"}, 1, primary=boom, elapsed_sec=0.0)
    assert source == "error_fallback"
    assert text == "B-fallback"
    assert primary.calls == 1


def test_llm_timeout_and_circuit_do_not_stall() -> None:
    primary = CountingLLM("slow")
    gateway = _gateway(primary, threshold=2)

    def call() -> str:
        primary.calls += 1
        return "should-not-use"

    text, source = gateway.decide_next_question(
        {1: "一", 2: "二"}, 1, primary=call, elapsed_sec=9.0, timeout_sec=3.0,
    )
    assert source == "timeout_fallback"
    assert text == "二"
    assert primary.calls == 0

    def boom() -> str:
        primary.calls += 1
        raise DomainError("LLM_PROVIDER_UNAVAILABLE", "fail")

    gateway.decide_next_question({1: "一", 2: "二"}, 1, primary=boom, elapsed_sec=0.0)
    gateway.decide_next_question({1: "一", 2: "二"}, 1, primary=boom, elapsed_sec=0.0)
    blocked = gateway.decide_next_question({1: "一", 2: "二"}, 1, primary=boom, elapsed_sec=0.0)
    assert blocked[1] == "circuit_fallback"
    assert blocked[0] == "二"


def test_asr_and_tts_failures_surface_speech_unavailable() -> None:
    settings = Settings(
        provider="fake",
        secret="fixture-" * 8,
        stt_provider="whisper",
        stt_model="base",
        stt_model_path="/tmp/unused.pt",
    )
    gateway = AIGateway(settings, CountingLLM("ok"), BoomASR(), BoomTTS())  # type: ignore[arg-type]
    with pytest.raises(DomainError) as asr_err:
        gateway.transcribe(b"RIFF____unused")
    assert asr_err.value.code == "SPEECH_UNAVAILABLE"

    with pytest.raises(DomainError) as tts_err:
        asyncio.run(gateway.synthesize("题目文本"))
    assert tts_err.value.code == "SPEECH_UNAVAILABLE"

    gateway.asr_circuit.record_failure()
    gateway.asr_circuit.record_failure()
    gateway.asr_circuit.record_failure()
    assert gateway.asr_circuit.is_open
    with pytest.raises(DomainError) as open_err:
        gateway.transcribe(b"x")
    assert open_err.value.code == "SPEECH_UNAVAILABLE"
