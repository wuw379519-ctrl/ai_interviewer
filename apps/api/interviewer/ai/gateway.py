"""AI Gateway: provider routing, circuit breaking, decision fallback, and metering."""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from typing import Literal, Protocol, TypeVar

import httpx

from interviewer import database as db
from interviewer.contracts import Contract, Object, SpeechOutput
from interviewer.errors import DomainError
from interviewer.provider import Generation
from interviewer.repository import StorageSession
from interviewer.settings import Settings

from .circuit import CircuitBreaker
from .fallback import rule_next_question
from .protocols import ASRProvider, LLMProvider, TTSProvider
from .usage import record_ai_usage

T = TypeVar("T", bound=Contract)
DecisionSource = Literal["primary", "timeout_fallback", "circuit_fallback", "error_fallback"]


class AIGateway:
    """Business code depends on this facade only; concrete providers stay behind factory."""

    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider,
        asr: ASRProvider,
        tts: TTSProvider,
        *,
        decision_timeout_sec: float = 3.0,
        llm_circuit: CircuitBreaker | None = None,
        asr_circuit: CircuitBreaker | None = None,
        tts_circuit: CircuitBreaker | None = None,
        tenant: str | None = None,
    ) -> None:
        self.settings = settings
        self._llm = llm
        self.asr = asr
        self.tts = tts
        self.decision_timeout_sec = decision_timeout_sec
        self.tenant = tenant
        # Mutable so tests can monkeypatch provider.name without a setter (Provider parity).
        self.name = llm.name
        self.model = llm.model
        self.llm_circuit = llm_circuit or CircuitBreaker()
        self.asr_circuit = asr_circuit or CircuitBreaker()
        self.tts_circuit = tts_circuit or CircuitBreaker()
        self.llm_primary_calls = 0

    def usage(self, prompt: int, completion: int) -> Object:
        return self._llm.usage(prompt, completion)

    def structured(
        self,
        operation: str,
        messages: list[dict[str, str]],
        schema: type[T],
        fixture: Object,
    ) -> Generation[T]:
        if not self.llm_circuit.allow():
            raise DomainError("LLM_PROVIDER_UNAVAILABLE", "模型熔断已打开，请稍后重试或使用规则兜底")
        self.llm_primary_calls += 1
        try:
            result = self._llm.structured(operation, messages, schema, fixture)
            self.llm_circuit.record_success()
            return result
        except Exception:
            self.llm_circuit.record_failure()
            raise

    def stream(self, text: str) -> Iterator[str]:
        if not self.llm_circuit.allow():
            # Text streaming is cosmetic; degrade to a single chunk so SSE never stalls.
            yield text
            return
        self.llm_primary_calls += 1
        try:
            yield from self._llm.stream(text)
            self.llm_circuit.record_success()
        except Exception:
            self.llm_circuit.record_failure()
            raise

    def decide_next_question(
        self,
        prompts_by_seq: Mapping[int, str],
        current_seq: int,
        *,
        primary: Callable[[], str] | None = None,
        elapsed_sec: float = 0.0,
        timeout_sec: float | None = None,
        connection: StorageSession | None = None,
    ) -> tuple[str, DecisionSource]:
        """LLM decision with injectable elapsed time; never blocks on real wall-clock waits in tests."""
        limit = self.decision_timeout_sec if timeout_sec is None else timeout_sec

        def fallback() -> str:
            return rule_next_question(prompts_by_seq, current_seq)

        if not self.llm_circuit.allow():
            return fallback(), "circuit_fallback"
        if elapsed_sec > limit:
            return fallback(), "timeout_fallback"
        if primary is None:
            return fallback(), "timeout_fallback"
        self.llm_primary_calls += 1
        try:
            text = primary()
            self.llm_circuit.record_success()
            if connection is not None:
                record_ai_usage(
                    connection,
                    provider=self.name,
                    kind="llm_tokens",
                    amount=0.0,
                    tenant=self.tenant,
                )
            return text, "primary"
        except Exception:
            self.llm_circuit.record_failure()
            return fallback(), "error_fallback"

    def transcribe(
        self,
        content: bytes,
        *,
        connection: StorageSession | None = None,
    ) -> str:
        settings = self.settings
        if not self.asr_circuit.allow():
            raise DomainError("SPEECH_UNAVAILABLE", "转写熔断已打开；可重试或改用文字")
        try:
            if settings.stt_provider == "whisper":
                text = self.asr.transcribe(content).text
                provider_name = self.asr.name
            elif settings.stt_base_url and settings.stt_model:
                text = self._http_transcribe(content)
                provider_name = "http_stt"
            else:
                raise DomainError("SPEECH_UNAVAILABLE", "尚未配置企业语音服务，请使用设备端识别或文字")
            self.asr_circuit.record_success()
        except DomainError:
            self.asr_circuit.record_failure()
            raise
        except (httpx.HTTPError, ValueError) as error:
            self.asr_circuit.record_failure()
            raise DomainError("SPEECH_UNAVAILABLE", "转写暂不可用，音频未保存；可重试或改用文字") from error
        if connection is not None:
            seconds = max(0.0, (len(content) - 44) / 32000)
            record_ai_usage(
                connection,
                provider=provider_name,
                kind="asr_seconds",
                amount=seconds,
                tenant=self.tenant,
            )
        return text

    def _http_transcribe(self, content: bytes) -> str:
        settings = self.settings
        with httpx.Client(timeout=settings.stt_timeout, follow_redirects=False, trust_env=False) as client:
            response = client.post(
                settings.stt_base_url.rstrip("/") + "/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.stt_key}"} if settings.stt_key else {},
                files={"file": ("answer.wav", content, "audio/wav")},
                data={"model": settings.stt_model, "language": "zh", "response_format": "json"},
            )
            response.raise_for_status()
            return SpeechOutput.model_validate_json(response.content).text

    async def synthesize(
        self,
        text: str,
        *,
        connection: StorageSession | None = None,
    ) -> bytes:
        if not self.tts_circuit.allow():
            raise DomainError("SPEECH_UNAVAILABLE", "播报熔断已打开，请阅读题目文字")
        try:
            audio = await self.tts.synthesize(text)
            self.tts_circuit.record_success()
        except Exception:
            self.tts_circuit.record_failure()
            raise
        if connection is not None:
            record_ai_usage(
                connection,
                provider=self.tts.name,
                kind="tts_chars",
                amount=float(len(text)),
                tenant=self.tenant,
            )
        return audio

    def meter(
        self,
        connection: StorageSession,
        kind: Literal["llm_tokens", "asr_seconds", "tts_chars"],
        amount: float,
        *,
        provider: str | None = None,
    ) -> db.Row:
        return record_ai_usage(
            connection,
            provider=provider or self.name,
            kind=kind,
            amount=amount,
            tenant=self.tenant,
        )

    def prepare_speech(self) -> None:
        if self.settings.stt_provider == "whisper":
            self.asr.load()
        if self.settings.tts_provider == "edge" and self.settings.tts_allow_external:
            self.tts.prepare()

    def close(self) -> None:
        self.asr.close()


class NullASR:
    name = "null_asr"

    def transcribe(self, content: bytes) -> SpeechOutput:
        raise DomainError("SPEECH_UNAVAILABLE", "尚未配置企业语音服务，请使用设备端识别或文字")

    def load(self) -> object:
        return self

    def close(self) -> None:
        return None


class NullTTS:
    name = "null_tts"

    def prepare(self) -> None:
        return None

    async def synthesize(self, text: str) -> bytes:
        raise DomainError("SPEECH_UNAVAILABLE", "题目播报未启用，请阅读题目文字")


class _WhisperLike(Protocol):
    def transcribe(self, content: bytes) -> SpeechOutput: ...

    def load(self) -> object: ...

    def close(self) -> None: ...


class _EdgeLike(Protocol):
    def prepare(self) -> None: ...

    async def synthesize(self, text: str) -> bytes: ...


class WhisperASRAdapter:
    """Adapts LocalWhisper to ASRProvider without exposing it to business modules."""

    def __init__(self, whisper: _WhisperLike) -> None:
        self._whisper = whisper
        self.name = "local_whisper"

    def transcribe(self, content: bytes) -> SpeechOutput:
        return self._whisper.transcribe(content)

    def load(self) -> object:
        return self._whisper.load()

    def close(self) -> None:
        self._whisper.close()

    @property
    def raw(self) -> _WhisperLike:
        return self._whisper


class EdgeTTSAdapter:
    def __init__(self, edge: _EdgeLike) -> None:
        self._edge = edge
        self.name = "edge"

    def prepare(self) -> None:
        self._edge.prepare()

    async def synthesize(self, text: str) -> bytes:
        return await self._edge.synthesize(text)

    @property
    def raw(self) -> _EdgeLike:
        return self._edge
