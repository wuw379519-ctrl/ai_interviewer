import asyncio
from pathlib import Path

import pytest

from interviewer import tts, tts_service
from interviewer.errors import DomainError
from interviewer.settings import Settings


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(tts_service, "ROOT", tmp_path)
    monkeypatch.setenv("ENABLE_EDGE_TTS", "true")
    monkeypatch.setattr(tts_service.Settings, "from_env", lambda: Settings(tts_provider="edge", tts_allow_external=True, tts_voice="synthetic-voice"))
    return tmp_path


@pytest.mark.parametrize("flag", [None, "false", "yes", "1"])
def test_disabled_by_default_without_importing_edge_or_loading_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], flag: str | None) -> None:
    monkeypatch.setattr(tts_service, "ROOT", tmp_path)
    if flag is None:
        monkeypatch.delenv("ENABLE_EDGE_TTS", raising=False)
    else:
        monkeypatch.setenv("ENABLE_EDGE_TTS", flag)
    monkeypatch.setattr(tts_service.Settings, "from_env", lambda: pytest.fail("disabled mode must not load providers"))
    monkeypatch.setattr(tts, "EdgeTTS", lambda *_args: pytest.fail("no Edge import or call allowed"))
    assert tts_service.generate_speech("合成题目") is None
    assert "纯文本" in capsys.readouterr().out
    assert not (tmp_path / ".data").exists()


def test_dotenv_flag_is_loaded_without_overriding_process_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(tts_service, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("ENABLE_EDGE_TTS=true\n", encoding="utf-8")
    monkeypatch.setenv("ENABLE_EDGE_TTS", "false")
    assert tts_service.generate_speech("合成题目") is None


def test_disabled_mode_also_works_inside_event_loop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(tts_service, "ROOT", tmp_path)
    monkeypatch.setenv("ENABLE_EDGE_TTS", "false")
    async def exercise() -> None:
        assert tts_service.generate_speech("合成题目") is None
        assert await tts_service.generate_speech_async("合成题目") is None
    asyncio.run(exercise())


def test_enabled_flag_cannot_bypass_existing_external_permission(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(tts_service, "ROOT", tmp_path)
    monkeypatch.setenv("ENABLE_EDGE_TTS", "true")
    monkeypatch.setattr(tts_service.Settings, "from_env", lambda: Settings(tts_provider="edge", tts_voice="fixture"))
    monkeypatch.setattr(tts, "EdgeTTS", lambda *_args: pytest.fail("external access not authorized"))
    assert tts_service.generate_speech("合成题目") is None


def test_success_writes_unique_local_mp3_and_returns_absolute_path(configured: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[str] = []
    class Provider:
        def __init__(self, _settings: Settings) -> None:
            pass
        async def synthesize(self, text: str) -> bytes:
            received.append(text)
            return b"synthetic-mp3"
    monkeypatch.setattr(tts, "EdgeTTS", Provider)
    paths = [Path(tts_service.generate_speech("合成题目") or "") for _ in range(2)]
    assert paths[0] != paths[1]
    assert all(path.is_absolute() and path.is_relative_to(configured / ".data" / "generated-speech") for path in paths)
    assert all(path.read_bytes() == b"synthetic-mp3" for path in paths)
    assert received == ["合成题目", "合成题目"]


@pytest.mark.parametrize("error", [DomainError("SPEECH_UNAVAILABLE", "sensitive upstream details"), ImportError("private location"), OSError("private location")])
def test_network_and_dependency_failures_fallback_without_leaking_details(configured: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], error: Exception) -> None:
    class Provider:
        def __init__(self, _settings: Settings) -> None:
            pass
        async def synthesize(self, _text: str) -> bytes:
            raise error
    monkeypatch.setattr(tts, "EdgeTTS", Provider)
    assert tts_service.generate_speech("synthetic private text") is None
    output = capsys.readouterr().out
    assert "纯文本" in output and "private" not in output and "sensitive" not in output


def test_sync_entry_explains_async_calling_contract(configured: Path) -> None:
    async def exercise() -> None:
        with pytest.raises(RuntimeError, match="generate_speech_async"):
            tts_service.generate_speech("合成题目")
    asyncio.run(exercise())
