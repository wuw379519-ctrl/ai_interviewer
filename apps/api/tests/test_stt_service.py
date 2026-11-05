import io
import subprocess
import wave
from pathlib import Path

import pytest

from interviewer import stt_service
from interviewer.contracts import SpeechOutput
from interviewer.errors import DomainError
from interviewer.settings import Settings


def wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\0\0" * 160)
    return output.getvalue()


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> tuple[stt_service.STTService, list[object]]:
    calls: list[object] = []
    class Provider:
        def __init__(self, settings: Settings) -> None:
            calls.append(settings.stt_model_path)
        def load(self) -> None:
            calls.append("loaded during initialization")
        def transcribe(self, data: bytes) -> SpeechOutput:
            calls.append(data)
            return SpeechOutput(text="合成文件转写")
        def close(self) -> None:
            calls.append("closed")
    monkeypatch.setattr(stt_service, "LocalWhisper", Provider)
    return stt_service.STTService(Settings(stt_model_path="fixture-local-weights")), calls


def test_initialization_loads_configured_model_and_pcm_wav_needs_no_ffmpeg(service: tuple[stt_service.STTService, list[object]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    instance, calls = service
    source = tmp_path / "合成 audio.wav"
    source.write_bytes(wav_bytes())
    monkeypatch.setattr(stt_service.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("standard WAV needs no ffmpeg"))
    assert calls == ["fixture-local-weights", "loaded during initialization"]
    assert instance.transcribe_audio(str(source)) == "合成文件转写"
    assert calls[-1] == source.read_bytes()


def test_other_formats_use_local_ffmpeg_and_normalize_pcm(service: tuple[stt_service.STTService, list[object]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    instance, calls = service
    source = tmp_path / "audio with spaces.mp3"
    source.write_bytes(b"synthetic compressed input")
    executable = tmp_path / "ffmpeg.exe"
    executable.touch()
    instance.settings.ffmpeg_path = str(executable)
    commands: list[list[str]] = []
    def decode(command: list[str], **options: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        assert options["shell"] is False and options["timeout"] == instance.settings.stt_timeout
        return subprocess.CompletedProcess(command, 0, stdout=b"\0\0" * 160, stderr=b"")
    monkeypatch.setattr(stt_service.subprocess, "run", decode)
    assert instance.transcribe_audio(str(source)) == "合成文件转写"
    assert commands[0][0] == str(executable)
    assert commands[0][commands[0].index("-i") + 1] == str(source.resolve())
    assert commands[0][commands[0].index("-protocol_whitelist") + 1] == "file,pipe"
    assert calls[-1] == wav_bytes()


def test_missing_ffmpeg_explains_process_path(service: tuple[stt_service.STTService, list[object]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "audio.mp3"
    source.write_bytes(b"synthetic")
    monkeypatch.setattr(stt_service.shutil, "which", lambda _name: None)
    with pytest.raises(DomainError, match="FFMPEG_PATH"):
        service[0].transcribe_audio(str(source))


@pytest.mark.parametrize("pcm", [b"", b"x", b"\0\0" * (16000 * 120 + 1)],
                         ids=["empty-pcm", "odd-byte-count", "over-120-seconds"])
def test_empty_invalid_and_overlong_audio_are_not_silently_transcribed(service: tuple[stt_service.STTService, list[object]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pcm: bytes) -> None:
    instance, calls = service
    source, executable = tmp_path / "audio.mp3", tmp_path / "ffmpeg.exe"
    source.write_bytes(b"fixture")
    executable.touch()
    instance.settings.ffmpeg_path = str(executable)
    monkeypatch.setattr(stt_service.subprocess, "run", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, stdout=pcm, stderr=b""))
    with pytest.raises(DomainError, match="120秒"):
        instance.transcribe_audio(str(source))
    assert calls == ["fixture-local-weights", "loaded during initialization"]


def test_converter_errors_do_not_expose_stderr(service: tuple[stt_service.STTService, list[object]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    instance, _ = service
    source, executable = tmp_path / "audio.mp3", tmp_path / "ffmpeg.exe"
    source.write_bytes(b"fixture")
    executable.touch()
    instance.settings.ffmpeg_path = str(executable)
    def fail(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "fixture", stderr=b"private path or audio metadata")
    monkeypatch.setattr(stt_service.subprocess, "run", fail)
    with pytest.raises(DomainError) as error:
        instance.transcribe_audio(str(source))
    assert "private" not in str(error.value)


@pytest.mark.parametrize("value", ["", "https://synthetic.invalid/audio.mp3", "\\\\synthetic.invalid\\share\\audio.wav"])
def test_only_local_existing_audio_paths_are_accepted(service: tuple[stt_service.STTService, list[object]], value: str) -> None:
    with pytest.raises(DomainError, match="本地音频"):
        service[0].transcribe_audio(value)


def test_function_initializes_once_and_reuses_service(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    class Service:
        def __init__(self) -> None:
            calls.append("init")
        def transcribe_audio(self, value: str) -> str:
            calls.append(value)
            return "合成结果"
    monkeypatch.setattr(stt_service, "_default", None)
    monkeypatch.setattr(stt_service, "STTService", Service)
    assert stt_service.transcribe_audio("fixture.wav") == "合成结果"
    assert stt_service.transcribe_audio("second.wav") == "合成结果"
    assert calls == ["init", "fixture.wav", "second.wav"]
