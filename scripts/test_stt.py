"""Explicit manual STT acceptance. Never run by CI or the pytest test suite."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from dotenv import load_dotenv
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
BEIJING = timezone(timedelta(hours=8))


class Transcript(BaseModel):
    text: str


def ensure_ffmpeg(configured: str, directory: Path) -> Path:
    candidates = [Path(configured)] if configured else []
    existing = shutil.which("ffmpeg")
    if existing:
        candidates.append(Path(existing))
    candidates.extend(Path(value) for value in [r"C:\ffmpeg\bin\ffmpeg.exe", r"D:\ffmpeg\bin\ffmpeg.exe",
                                               r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"])
    for environment in [".venv311", ".venv"]:
        candidates.extend(sorted((ROOT / environment / "Lib/site-packages/imageio_ffmpeg/binaries").glob("*ffmpeg*.exe")))
    executable = next((path.resolve() for path in candidates if path.is_file()), None)
    if executable is None:
        raise RuntimeError("未找到已有FFmpeg，请配置.env的FFMPEG_PATH；脚本不会下载安装")
    expected = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if executable.name.lower() != expected:
        binary = directory / "bin"
        binary.mkdir()
        alias = binary / expected
        try:
            os.link(executable, alias)
        except OSError:
            shutil.copyfile(executable, alias)
            alias.chmod(executable.stat().st_mode)
        executable = alias
    # Prepend only to this process: Whisper's subprocess calls use the bare name ffmpeg.
    os.environ["PATH"] = str(executable.parent) + os.pathsep + os.environ.get("PATH", "")
    subprocess.run([str(executable), "-version"], check=True, capture_output=True, timeout=10)
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg已发现，但PATH注入验证失败")
    return executable


def convert_audio(source: Path, target: Path, ffmpeg: Path, timeout: float) -> None:
    subprocess.run([str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
                    "-protocol_whitelist", "file,pipe", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", str(target)], check=True, capture_output=True, timeout=timeout)


def main() -> None:
    parser = argparse.ArgumentParser(description="仅手工执行的授权本地音频Whisper测试；不会上传、下载或写入候选人问答。")
    parser.add_argument("--audio", type=Path, default=ROOT / ".data/acceptance/voice/authorized-synthetic-zh.wav")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    sys.path.insert(0, str(ROOT / "apps/api"))
    from interviewer.local_whisper import LocalWhisper
    from interviewer.settings import Settings

    settings = Settings.from_env()
    source = args.audio.expanduser().resolve()
    if not source.is_file() or source.anchor.startswith("\\\\"):
        parser.error("请提供已有本地授权音频；不接受URL或网络共享")
    if not settings.stt_model_path or not Path(settings.stt_model_path).is_file():
        parser.error("STT_MODEL_PATH必须指向已有本地权重文件；不会自动下载")
    directory = ROOT / ".data/acceptance/voice" / ("stt-run-" + uuid4().hex)
    directory.mkdir(parents=True, exist_ok=False)
    ffmpeg = ensure_ffmpeg(settings.ffmpeg_path, directory)
    print("Python:", sys.version.split()[0], flush=True)
    print("FFmpeg PATH注入已验证:", ffmpeg, flush=True)
    provider = LocalWhisper(settings)
    # Real Whisper runs below. Only Python network sockets are blocked, never model inference.
    with patch("socket.socket.connect", side_effect=RuntimeError("本次STT测试禁止联网")), \
            patch("socket.create_connection", side_effect=RuntimeError("本次STT测试禁止联网")):
        try:
            model_start = time.perf_counter()
            model = provider.load()
            model_seconds = time.perf_counter() - model_start
            started_at = datetime.now(BEIJING).isoformat(timespec="milliseconds")
            print("识别开始时间（北京时间）:", started_at, flush=True)
            start = time.perf_counter()
            retried = False
            try:
                raw = model.transcribe(str(source), language=settings.stt_language, fp16=False, verbose=None,
                                       temperature=0.0, condition_on_previous_text=False)
            except (RuntimeError, OSError) as error:
                if not any(word in str(error).lower() for word in ["ffmpeg", "audio", "decode", "format", "codec", "sample rate"]):
                    raise
                print("音频读取/格式兼容失败，正在本地转码为16kHz单声道PCM WAV后重试。", flush=True)
                converted = directory / "converted-16k-mono.wav"
                convert_audio(source, converted, ffmpeg, settings.stt_timeout)
                retried = True
                raw = model.transcribe(str(converted), language=settings.stt_language, fp16=False, verbose=None,
                                       temperature=0.0, condition_on_previous_text=False)
            text = Transcript.model_validate(raw).text.strip()
            seconds = time.perf_counter() - start
            ended_at = datetime.now(BEIJING).isoformat(timespec="milliseconds")
        finally:
            provider.close()
    print("识别结束时间（北京时间）:", ended_at, flush=True)
    print("【识别出的完整文本】", flush=True)
    print(text if text else "（未识别到语音，结果为空）", flush=True)
    print(f"【转录耗时】{seconds:.3f} 秒（不含模型加载）", flush=True)
    print(f"【模型加载耗时】{model_seconds:.3f} 秒", flush=True)
    with source.open("rb") as audio:
        digest = hashlib.file_digest(audio, "sha256").hexdigest()
    evidence = {"python": sys.version.split()[0], "audioSha256": digest, "startedAt": started_at, "endedAt": ended_at,
                "transcriptionSeconds": seconds, "modelLoadSeconds": model_seconds, "formatRetry": retried,
                "pythonNetworkBlocked": True, "text": text}
    (directory / "private-result.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print("私有结果文件:", directory / "private-result.json", flush=True)


if __name__ == "__main__":
    main()
