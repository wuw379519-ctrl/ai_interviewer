from pathlib import Path

import pytest

from interviewer import settings
from interviewer.settings import Settings


@pytest.fixture
def config_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(settings, "ROOT", root)
    monkeypatch.setenv("DB_DRIVER", "sqlite")
    return root


def test_relative_asset_paths_follow_repository_across_working_directories(
    config_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STT_MODEL_PATH", "")
    monkeypatch.setenv("FFMPEG_PATH", "")
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    (config_root / ".env").write_text(
        "STT_MODEL_PATH=.data/models/../models/whisper/base.pt\n"
        "FFMPEG_PATH=.data/tools/ffmpeg.exe\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SQLITE_PATH", "relative.sqlite3")

    for directory in (config_root, config_root.parent):
        monkeypatch.delenv("STT_MODEL_PATH", raising=False)
        monkeypatch.delenv("FFMPEG_PATH", raising=False)
        monkeypatch.chdir(directory)
        loaded = Settings.from_env()
        assert loaded.stt_model_path == str((config_root / ".data/models/whisper/base.pt").resolve())
        assert loaded.ffmpeg_path == str((config_root / ".data/tools/ffmpeg.exe").resolve())
        assert loaded.sqlite_path == "relative.sqlite3"


def test_absolute_asset_paths_are_preserved(config_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = config_root.parent.as_posix()
    model = outside + "/assets/../base.pt"
    ffmpeg = outside + "/tools/../ffmpeg.exe"
    monkeypatch.setenv("STT_MODEL_PATH", model)
    monkeypatch.setenv("FFMPEG_PATH", ffmpeg)

    loaded = Settings.from_env()
    assert loaded.stt_model_path == model
    assert loaded.ffmpeg_path == ffmpeg


def test_empty_asset_paths_stay_empty(config_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STT_MODEL_PATH", "")
    monkeypatch.setenv("FFMPEG_PATH", "")

    loaded = Settings.from_env()
    assert loaded.stt_model_path == ""
    assert loaded.ffmpeg_path == ""


def test_user_home_asset_paths_are_expanded(config_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STT_MODEL_PATH", "~/assets/base.pt")
    monkeypatch.setenv("FFMPEG_PATH", "~/tools/ffmpeg.exe")

    loaded = Settings.from_env()
    assert loaded.stt_model_path == str((Path.home() / "assets/base.pt").resolve())
    assert loaded.ffmpeg_path == str((Path.home() / "tools/ffmpeg.exe").resolve())
