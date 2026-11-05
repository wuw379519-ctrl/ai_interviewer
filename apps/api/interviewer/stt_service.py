"""Local audio-file STT facade; importing this module never loads/downloads a model."""
from __future__ import annotations

import io
import shutil
import subprocess
import threading
import wave
from pathlib import Path

from .errors import DomainError
from .local_whisper import LocalWhisper
from .settings import Settings
from .speech import validate_wave

MAX_FILE_BYTES = 16 * 1024 * 1024
_default: STTService | None = None
_default_lock = threading.Lock()


def _pcm_wave(pcm: bytes) -> bytes:
    if not pcm or len(pcm) % 2 or len(pcm) > 16000 * 2 * 120:
        raise DomainError("VALIDATION_FAILED", "音频为空、解码无效或超过120秒，请分段处理")
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(pcm)
    content = output.getvalue()
    validate_wave(content)
    return content


def _convert_wave(settings: Settings, source: str, protocols: str, uploaded: bytes | None = None) -> bytes:
    executable = settings.ffmpeg_path or shutil.which("ffmpeg")
    if not executable or not Path(executable).is_file():
        raise DomainError("SPEECH_UNAVAILABLE", "当前进程找不到ffmpeg，请配置FFMPEG_PATH或重新打开已更新PATH的终端")
    try:
        # Decode up to 121 seconds so the existing 120-second limit rejects overlong audio.
        result = subprocess.run([executable, "-nostdin", "-hide_banner", "-loglevel", "error",
                                 "-protocol_whitelist", protocols, "-i", source, "-vn", "-t", "121",
                                 "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"],
                                stdin=subprocess.DEVNULL if uploaded is None else None, input=uploaded,
                                capture_output=True, timeout=settings.stt_timeout, check=True, shell=False)
    except (OSError, subprocess.SubprocessError):
        raise DomainError("SPEECH_UNAVAILABLE", "本地ffmpeg解码失败或超时；请检查音频格式和可执行文件") from None
    return _pcm_wave(result.stdout)


def uploaded_wave(settings: Settings, content: bytes) -> bytes:
    if not 0 < len(content) <= MAX_FILE_BYTES:
        raise DomainError("VALIDATION_FAILED", "音频文件须非空且不超过16MiB")
    try:
        validate_wave(content)
    except DomainError:
        return _convert_wave(settings, "pipe:0", "pipe", content)
    return content


class STTService:
    def __init__(self, settings: Settings | None = None) -> None:
        # Settings.from_env uses python-dotenv on the repository root .env, override=False.
        self.settings = settings or Settings.from_env()
        self._provider = LocalWhisper(self.settings)
        try:
            # Existing absolute file only, never the model alias "base" or a URL.
            self._provider.load()
        except Exception:
            self._provider.close()
            raise

    def _wave(self, source: Path) -> bytes:
        if source.suffix.lower() == ".wav":
            content = source.read_bytes()
            try:
                validate_wave(content)
                return content
            except DomainError:
                pass  # Other WAV encodings/sample rates go through the same local converter.
        return _convert_wave(self.settings, str(source), "file,pipe")

    def transcribe_audio(self, audio_path: str) -> str:
        source = Path(audio_path).expanduser()
        if not audio_path or source.anchor.startswith("\\\\") or not source.is_file():
            raise DomainError("VALIDATION_FAILED", "请提供已有本地音频文件路径，不接受URL或网络共享路径")
        if not 0 < source.stat().st_size <= MAX_FILE_BYTES:
            raise DomainError("VALIDATION_FAILED", "音频文件须非空且不超过16MiB")
        return self._provider.transcribe(self._wave(source.resolve())).text

    def close(self) -> None:
        self._provider.close()


def transcribe_audio(audio_path: str) -> str:
    """Initialize the configured local model once, then transcribe a local audio file."""
    global _default
    with _default_lock:
        if _default is None:
            _default = STTService()
        service = _default
    return service.transcribe_audio(audio_path)
