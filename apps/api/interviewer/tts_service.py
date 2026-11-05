"""Isolated optional TTS facade for approved fixed questions/local synthetic tests."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from .errors import DomainError
from .settings import ROOT, Settings


def _configuration() -> Settings | None:
    load_dotenv(ROOT / ".env", override=False)
    if os.getenv("ENABLE_EDGE_TTS", "false").strip().lower() != "true":
        print("Edge TTS未启用（ENABLE_EDGE_TTS=false），使用纯文本输出。")
        return None
    settings = Settings.from_env()
    if settings.tts_provider != "edge" or not settings.tts_allow_external or not settings.tts_voice:
        print("Edge TTS尚未配置外网许可或音色：需TTS_PROVIDER=edge、TTS_ALLOW_EXTERNAL=true和TTS_VOICE；使用纯文本。")
        return None
    return settings


async def _generate(text: str, settings: Settings) -> str | None:
    target: Path | None = None
    created = False
    try:
        # edge_tts itself is imported lazily by EdgeTTS.prepare(), only after every flag check.
        from .tts import EdgeTTS
        audio = await EdgeTTS(settings).synthesize(text)
        directory = ROOT / ".data" / "generated-speech"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{uuid4()}.mp3"
        with target.open("xb") as output:
            created = True
            output.write(audio)
        return str(target.resolve())
    except (DomainError, ImportError, OSError):
        if created and target is not None:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
        # No input text, upstream exception, token, or local path is logged.
        print("Edge TTS依赖、网络或音频写入不可用，使用纯文本输出。")
        return None


async def generate_speech_async(text: str) -> str | None:
    """Use from asynchronous callers. Do not pass candidate answers or resumes."""
    settings = _configuration()
    return await _generate(text, settings) if settings is not None else None


def generate_speech(text: str) -> str | None:
    """Return an MP3 path or None; disabled mode imports no optional speech library."""
    settings = _configuration()
    if settings is None:
        return None
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_generate(text, settings))
    raise RuntimeError("异步调用方请使用await generate_speech_async(text)，避免阻塞FastAPI事件循环")
