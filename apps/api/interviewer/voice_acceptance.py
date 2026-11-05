"""Explicit manual acceptance only; never imported by the server or CI tests."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

from .local_whisper import LocalWhisper
from .settings import ROOT, Settings
from .speech import validate_wave
from .tts import EdgeTTS


def main() -> None:
    parser = argparse.ArgumentParser(description="手工语音验收；不要输入真实候选人资料。不会下载或安装模型/依赖。")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--whisper", action="store_true", help="加载配置的已有本地Whisper；可选转写合成WAV")
    mode.add_argument("--edge", action="store_true", help="实际调用微软在线播报，仅发送脚本固定测试句")
    parser.add_argument("--audio", type=Path, help="仅Whisper：已准备的16kHz单声道PCM WAV合成音频")
    parser.add_argument("--allow-public-edge", action="store_true", help="明确允许此次固定句的公网手工测试")
    args = parser.parse_args()
    settings = Settings.from_env()
    started = time.perf_counter()
    evidence: dict[str, object] = {"manualOnly": True}
    output = ROOT / ".data" / "acceptance" / "voice" / str(uuid4())
    if args.whisper:
        if settings.stt_provider != "whisper":
            parser.error("请先配置STT_PROVIDER=whisper和本地权重；不会下载模型")
        provider = LocalWhisper(settings)
        try:
            provider.load()
            evidence.update(provider="local_whisper", model=settings.stt_model, device=settings.stt_device)
            with Path(settings.stt_model_path).open("rb") as weights:
                evidence["weightsSha256"] = hashlib.file_digest(weights, "sha256").hexdigest()
            if args.audio:
                content = args.audio.read_bytes()
                validate_wave(content)
                result = provider.transcribe(content)
                evidence.update(audioSha256=hashlib.sha256(content).hexdigest(),
                                audioSeconds=(len(content) - 44) / 32000, recognizedCharacters=len(result.text))
                # Private manual artifact only, not a candidate turn or a committed evidence fixture.
                output.mkdir(parents=True, exist_ok=False)
                (output / "private-transcript.txt").write_text(result.text, encoding="utf-8")
        finally:
            provider.close()
    else:
        if not args.allow_public_edge or args.audio:
            parser.error("Edge必须显式传--allow-public-edge；不接受音频/候选人文本")
        audio = asyncio.run(EdgeTTS(settings).synthesize("你好，这是一段合成语音测试，请确认能否听到中文题目。"))
        output.mkdir(parents=True, exist_ok=False)
        (output / "question.mp3").write_bytes(audio)
        evidence.update(provider="edge", voice=settings.tts_voice, bytes=len(audio), candidateContentSent=False)
    evidence["durationMs"] = round((time.perf_counter() - started) * 1000)
    output.mkdir(parents=True, exist_ok=True)
    (output / "result.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "privateEvidence": str(output), **evidence}, ensure_ascii=False))


if __name__ == "__main__":
    main()
