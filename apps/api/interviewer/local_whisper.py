"""Local-only Whisper loading. No model names are passed to Whisper's downloader."""
from __future__ import annotations

import hashlib
import importlib
import io
import threading
import wave
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Protocol, cast
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .contracts import SpeechOutput
from .errors import DomainError
from .settings import Settings


class WhisperModel(Protocol):
    def transcribe(self, audio: object, **options: object) -> object: ...


class WhisperModule(Protocol):
    def load_model(self, name: str, *, device: str) -> WhisperModel: ...


class Samples(Protocol):
    def astype(self, dtype: str) -> Samples: ...
    def __truediv__(self, scale: float) -> object: ...


class NumpyModule(Protocol):
    def frombuffer(self, data: bytes, *, dtype: str) -> Samples: ...


class WhisperResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str = Field(max_length=4000)

    @field_validator("text")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("No recognized speech")
        return value.strip()


def load_model(path: str, device: str) -> WhisperModel:
    try:
        module = cast(WhisperModule, importlib.import_module("whisper"))
    except ImportError as error:
        raise DomainError("SPEECH_UNAVAILABLE", "当前Python环境缺少已有Whisper运行依赖，请配置正确的离线环境") from error
    return module.load_model(path, device=device)


def decode_wave(content: bytes) -> object:
    numpy = cast(NumpyModule, importlib.import_module("numpy"))
    with wave.open(io.BytesIO(content), "rb") as audio:
        pcm = audio.readframes(audio.getnframes())
    # Already validated 16kHz mono PCM; ndarray avoids FFmpeg and audio files on disk.
    return numpy.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0


class LocalWhisper:
    def __init__(self, settings: Settings, loader: Callable[[str, str], WhisperModel] = load_model,
                 decoder: Callable[[bytes], object] = decode_wave) -> None:
        self.settings, self._loader, self._decoder = settings, loader, decoder
        self._model: WhisperModel | None = None
        self._signature: tuple[str, int, int, str] | None = None
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(settings.stt_max_concurrency)
        self._executor = ThreadPoolExecutor(max_workers=settings.stt_max_concurrency, thread_name_prefix="local-whisper")

    def load(self) -> WhisperModel:
        with self._lock:
            if not self.settings.stt_model_path:
                raise DomainError("SPEECH_UNAVAILABLE", "请配置STT_MODEL_PATH指向已有本地权重；不会自动下载")
            path = Path(self.settings.stt_model_path).expanduser().resolve()
            if not path.is_file():
                raise DomainError("SPEECH_UNAVAILABLE", "本地Whisper权重不存在；不会自动下载")
            info = path.stat()
            signature = (str(path), info.st_mtime_ns, info.st_size, self.settings.stt_device)
            if self._model is not None:
                if signature != self._signature:
                    raise DomainError("SPEECH_UNAVAILABLE", "Whisper权重或设备配置已改变，请重启服务后重新加载")
                return self._model
            if self.settings.stt_model_sha256:
                with path.open("rb") as source:
                    digest = hashlib.file_digest(source, "sha256").hexdigest()
                if digest != self.settings.stt_model_sha256:
                    raise DomainError("SPEECH_UNAVAILABLE", "Whisper权重校验失败")
            # An absolute existing file path selects Whisper's file branch, never _download().
            try:
                self._model = self._loader(str(path), self.settings.stt_device)
            except DomainError:
                raise
            except Exception:
                raise DomainError("SPEECH_UNAVAILABLE", "本地Whisper权重或设备加载失败，请检查离线环境") from None
            self._signature = signature
            return self._model

    def _run(self, content: bytes) -> SpeechOutput:
        # One model is serialized: Whisper decoding installs temporary model hooks.
        with self._lock:
            model = self.load()
            options: dict[str, object] = {"language": self.settings.stt_language, "fp16": False, "verbose": None,
                                          "temperature": 0.0, "condition_on_previous_text": False}
            if self.settings.stt_initial_prompt.strip():
                options["initial_prompt"] = self.settings.stt_initial_prompt
            result = model.transcribe(self._decoder(content), **options)
            return SpeechOutput(text=WhisperResult.model_validate(result).text)

    def transcribe(self, content: bytes) -> SpeechOutput:
        if not self._slots.acquire(blocking=False):
            raise DomainError("SPEECH_UNAVAILABLE", "本地转写繁忙，请稍后重试或使用文字")
        try:
            future = self._executor.submit(self._run, content)
        except RuntimeError as error:
            self._slots.release()
            raise DomainError("SPEECH_UNAVAILABLE", "本地转写服务已关闭") from error
        future.add_done_callback(lambda _done: self._slots.release())
        try:
            return future.result(timeout=self.settings.stt_timeout)
        except TimeoutError as error:
            future.cancel()
            raise DomainError("SPEECH_UNAVAILABLE", "本地转写超时，可改用文字；正在运行的推理结束前不会释放占用") from error
        except DomainError:
            raise
        except Exception as error:
            raise DomainError("SPEECH_UNAVAILABLE", "本地Whisper转写失败，未保存音频，可重试或改用文字") from error

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
