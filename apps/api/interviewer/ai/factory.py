"""Construct the AIGateway. The only module allowed to import concrete provider classes for wiring."""
from __future__ import annotations

from interviewer.local_whisper import LocalWhisper
from interviewer.provider import Provider
from interviewer.settings import Settings
from interviewer.tts import EdgeTTS

from .gateway import AIGateway, EdgeTTSAdapter, WhisperASRAdapter


def build_gateway(
    settings: Settings,
    *,
    llm: Provider | None = None,
    whisper: LocalWhisper | None = None,
    edge: EdgeTTS | None = None,
) -> tuple[AIGateway, LocalWhisper, EdgeTTS]:
    """Return gateway plus the concrete ASR/TTS instances Service keeps for lifespan and tests."""
    primary = llm or Provider(settings)
    asr_impl = whisper if whisper is not None else LocalWhisper(settings)
    tts_impl = edge if edge is not None else EdgeTTS(settings)
    gateway = AIGateway(
        settings,
        primary,
        WhisperASRAdapter(asr_impl),
        EdgeTTSAdapter(tts_impl),
    )
    return gateway, asr_impl, tts_impl
