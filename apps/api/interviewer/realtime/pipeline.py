"""Audio → ASR → service.turn → TTS → tts_chunk (Task 6b).

Orchestration reuses service.turn (via write_with_key + idempotency_keys) so WS
does not fork question/followup/wrap logic. Gateway calls follow D73 (async
surface wrapping sync ASR).
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import struct
import time
import wave
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import uuid4

from interviewer import database as db
from interviewer import events
from interviewer.contracts import TurnInput
from interviewer.errors import DomainError
from interviewer.realtime.protocol import (
    MAX_AUDIO_CHUNK_PCM_BYTES,
    AudioChunkMessage,
    EndTurnMessage,
    ErrorMessage,
    FinalTranscriptMessage,
    InterruptedMessage,
    PartialTranscriptMessage,
    QuestionMessage,
    StateChangedMessage,
    TextInputMessage,
)
from interviewer.realtime.session_store import LiveSession
from interviewer.realtime.tts_player import TtsPlayer
from interviewer.realtime.vad import EnergyVad
from interviewer.service import Service
from interviewer.tenancy import reset_current_tenant, set_current_tenant

logger = logging.getLogger("interviewer.realtime.pipeline")

SendFn = Callable[[object], Awaitable[None]]
WS_TURN_SCOPE = "WS /turns"


@dataclass
class LatencySample:
    asr_first_ms: float | None = None
    llm_first_ms: float | None = None
    tts_first_ms: float | None = None
    e2e_ms: float | None = None


@dataclass
class InterruptTiming:
    vad_onset_mono: float
    interrupted_sent_mono: float

    @property
    def silence_ms(self) -> float:
        return (self.interrupted_sent_mono - self.vad_onset_mono) * 1000.0


@dataclass
class RealtimePipeline:
    service: Service
    session: LiveSession
    send: SendFn
    vad: EnergyVad = field(default_factory=EnergyVad)
    player: TtsPlayer | None = None
    pcm_buffer: bytearray = field(default_factory=bytearray)
    last_audio_seq: int = -1
    generation: int = 0
    turn_task: asyncio.Task[None] | None = None
    last_latency: LatencySample | None = None
    last_interrupt: InterruptTiming | None = None
    latency_log: list[LatencySample] = field(default_factory=list)
    cancelled: bool = False

    def __post_init__(self) -> None:
        if self.player is None:
            self.player = TtsPlayer(send=self.send)

    def cancel(self) -> None:
        """Supersede / disconnect: abandon in-flight turn; do not write results."""
        self.cancelled = True
        self.generation += 1
        assert self.player is not None
        self.player.cancel()
        if self.turn_task is not None and not self.turn_task.done():
            self.turn_task.cancel()
        self.turn_task = None
        self.pcm_buffer.clear()
        self.vad.reset()

    async def handle_audio_chunk(self, message: AudioChunkMessage) -> None:
        if message.seq <= self.last_audio_seq:
            await self.send(ErrorMessage(code="VALIDATION_FAILED", message="audio_chunk.seq 必须严格递增"))
            return
        self.last_audio_seq = message.seq
        pcm = b""
        if message.pcm_base64:
            try:
                pcm = base64.b64decode(message.pcm_base64, validate=True)
            except Exception:
                await self.send(ErrorMessage(code="VALIDATION_FAILED", message="pcmBase64 无效"))
                return
            if len(pcm) > MAX_AUDIO_CHUNK_PCM_BYTES:
                await self.send(ErrorMessage(code="VALIDATION_FAILED", message="单片 PCM 超过 32000 字节上限"))
                return
            if len(pcm) % 2:
                await self.send(ErrorMessage(code="VALIDATION_FAILED", message="PCM 字节数须为偶数"))
                return
            self.pcm_buffer.extend(pcm)
        if pcm:
            decision = self.vad.push(pcm)
            assert self.player is not None
            if decision.just_started and self.player.playing:
                await self.barge_in(onset_mono=time.perf_counter())

    async def handle_text_input(self, message: TextInputMessage) -> None:
        self._spawn_turn(
            transcript=message.text,
            idempotency_key=message.idempotency_key,
            expected_question_seq=message.expected_question_seq,
            from_audio=False,
        )

    async def handle_end_turn(self, message: EndTurnMessage) -> None:
        key = message.idempotency_key or f"ws-end-{uuid4()}"
        if not self.pcm_buffer:
            await self.send(ErrorMessage(code="VALIDATION_FAILED", message="没有可转写的音频缓冲"))
            return
        self._spawn_turn(
            transcript=None,
            idempotency_key=key,
            expected_question_seq=None,
            from_audio=True,
        )

    async def handle_client_interrupt(self) -> None:
        await self.barge_in(onset_mono=time.perf_counter(), reason="client")

    async def barge_in(
        self,
        *,
        onset_mono: float,
        reason: str = "vad_barge_in",
    ) -> None:
        assert self.player is not None
        self.generation += 1
        gen = self.generation
        self.player.cancel()
        self.player.bump_generation(gen)
        if self.turn_task is not None and not self.turn_task.done():
            self.turn_task.cancel()
        self.turn_task = None
        at = db.iso(db.now())
        interrupt_reason: str = reason if reason in {"vad_barge_in", "client", "device_lost"} else "vad_barge_in"
        token = set_current_tenant(self.session.tenant_id)
        try:
            with self.service.database.unit_of_work() as connection:
                events.append_event(
                    connection,
                    self.session.interview_id,
                    "interrupted",
                    {
                        "reason": interrupt_reason,
                        "source": "ws_vad" if interrupt_reason == "vad_barge_in" else "ws_client",
                    },
                )
        finally:
            reset_current_tenant(token)
        await self.send(
            InterruptedMessage(
                at=at,
                reason=interrupt_reason,  # type: ignore[arg-type]
            )
        )
        sent = time.perf_counter()
        self.last_interrupt = InterruptTiming(vad_onset_mono=onset_mono, interrupted_sent_mono=sent)
        self.vad.reset()

    def _spawn_turn(
        self,
        *,
        transcript: str | None,
        idempotency_key: str,
        expected_question_seq: int | None,
        from_audio: bool,
    ) -> None:
        """Fire-and-forget so the WS receive loop stays responsive (barge-in / supersede)."""
        if self.cancelled:
            return
        self.generation += 1
        gen = self.generation
        if self.turn_task is not None and not self.turn_task.done():
            self.turn_task.cancel()
        self.turn_task = asyncio.create_task(
            self._run_turn(
                transcript=transcript,
                idempotency_key=idempotency_key,
                expected_question_seq=expected_question_seq,
                from_audio=from_audio,
                generation=gen,
            )
        )

    async def _run_turn(
        self,
        *,
        transcript: str | None,
        idempotency_key: str,
        expected_question_seq: int | None,
        from_audio: bool,
        generation: int,
    ) -> None:
        sample = LatencySample()
        t0 = time.perf_counter()
        text = transcript or ""
        if from_audio:
            pcm = bytes(self.pcm_buffer)
            self.pcm_buffer.clear()
            wav = pcm16le_to_wav(pcm)
            try:
                text = await asyncio.to_thread(self._transcribe, wav)
            except DomainError as error:
                await self.send(ErrorMessage(code=error.code, message=error.message))
                return
            except Exception:
                logger.exception("asr_failed")
                await self.send(ErrorMessage(code="SPEECH_UNAVAILABLE", message="转写失败，请改用文字回答"))
                return
            if generation != self.generation or self.cancelled:
                return
            sample.asr_first_ms = (time.perf_counter() - t0) * 1000.0
            # Fake/local ASR returns full text at once — first char == final.
            await self.send(PartialTranscriptMessage(text=text[: max(1, min(8, len(text)))]))
            await self.send(FinalTranscriptMessage(text=text))
        else:
            sample.asr_first_ms = 0.0
            await self.send(FinalTranscriptMessage(text=text))

        if generation != self.generation or self.cancelled:
            return

        t_llm0 = time.perf_counter()
        try:
            result_payload = await asyncio.to_thread(
                self._commit_turn,
                text,
                idempotency_key,
                expected_question_seq,
            )
        except DomainError as error:
            await self.send(ErrorMessage(code=error.code, message=error.message))
            return
        except Exception:
            logger.exception("turn_failed")
            await self.send(ErrorMessage(code="INTERNAL_ERROR", message="编排失败"))
            return

        if generation != self.generation or self.cancelled:
            # In-flight result discarded on supersede / barge-in after DB write:
            # idempotency key already stored; reconnect must not double-ask via same key.
            return

        sample.llm_first_ms = (time.perf_counter() - t_llm0) * 1000.0
        utterance = str(result_payload.get("text") or "")
        q_seq = int(str(result_payload.get("questionSeq") or 1))
        await self.send(
            QuestionMessage(questionSeq=q_seq, text=utterance, intent=str(result_payload.get("kind") or ""))
        )
        await self.send(
            StateChangedMessage(
                status=str(result_payload.get("status") or "interviewing"),
                detail={"via": "ws_turn", "kind": result_payload.get("kind")},
            )
        )

        t_tts0 = time.perf_counter()
        try:
            audio = await self.service.gateway.synthesize(utterance)
        except DomainError as error:
            await self.send(ErrorMessage(code=error.code, message=error.message))
            sample.tts_first_ms = None
            sample.e2e_ms = (time.perf_counter() - t0) * 1000.0
            self.last_latency = sample
            self.latency_log.append(sample)
            return
        except Exception:
            logger.exception("tts_failed")
            await self.send(ErrorMessage(code="SPEECH_UNAVAILABLE", message="播报失败，请阅读题目文字"))
            sample.e2e_ms = (time.perf_counter() - t0) * 1000.0
            self.last_latency = sample
            self.latency_log.append(sample)
            return

        if generation != self.generation or self.cancelled:
            return

        assert self.player is not None
        # Measure TTS first byte as first chunk send — wrap send temporarily.
        first_byte_holder: dict[str, float] = {}
        recorded = False

        async def timed_send(message: object) -> None:
            nonlocal recorded
            if first_byte_holder.get("t") is None and getattr(message, "type", None) == "tts_chunk":
                first_byte_holder["t"] = time.perf_counter()
                sample.tts_first_ms = (first_byte_holder["t"] - t_tts0) * 1000.0
                sample.e2e_ms = (first_byte_holder["t"] - t0) * 1000.0
                self.last_latency = sample
                if not recorded:
                    self.latency_log.append(sample)
                    recorded = True
            await self.send(message)

        self.player.send = timed_send
        await self.player.play(audio, generation=generation)
        if not recorded:
            sample.tts_first_ms = (time.perf_counter() - t_tts0) * 1000.0
            sample.e2e_ms = (time.perf_counter() - t0) * 1000.0
            self.last_latency = sample
            self.latency_log.append(sample)

    def _transcribe(self, wav: bytes) -> str:
        return self.service.gateway.transcribe(wav)

    def _commit_turn(
        self,
        text: str,
        idempotency_key: str,
        expected_question_seq: int | None,
    ) -> dict[str, object]:
        body = TurnInput(
            action="answer",
            content=text,
            expected_question_seq=expected_question_seq,
        )
        token = set_current_tenant(self.session.tenant_id)
        try:
            with self.service.database.unit_of_work() as connection:
                result = self.service.write_with_key(
                    connection,
                    WS_TURN_SCOPE,
                    idempotency_key,
                    body,
                    lambda: self.service.turn(connection, self.session.interview_id, body),
                    interview_id=self.session.interview_id,
                )
                return dict(result.payload)
        finally:
            reset_current_tenant(token)


def pcm16le_to_wav(pcm: bytes, sample_rate: int = 16_000) -> bytes:
    """Wrap raw PCM16LE mono into a WAV container for gateway.transcribe."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)
    return buffer.getvalue()


def sine_pcm16le(duration_ms: int = 200, sample_rate: int = 16_000, hz: float = 440.0, amplitude: int = 8000) -> bytes:
    """Synthetic tone for VAD / latency tests (no real mic)."""
    import math

    n = int(sample_rate * duration_ms / 1000)
    out = bytearray()
    for i in range(n):
        sample = int(amplitude * math.sin(2 * math.pi * hz * i / sample_rate))
        out.extend(struct.pack("<h", max(-32767, min(32767, sample))))
    return bytes(out)
