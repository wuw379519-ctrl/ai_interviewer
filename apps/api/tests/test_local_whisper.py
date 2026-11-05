import io
import threading
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typing import cast

from interviewer.contracts import SpeechOutput, json_object
from interviewer.errors import DomainError
from interviewer.local_whisper import LocalWhisper
from interviewer.main import create_app
from interviewer.service import Service
from interviewer.settings import Settings
from conftest import invitation


def audio() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x01\x00" * 1600)
    return output.getvalue()


def configuration(tmp_path: Path) -> Settings:
    weights = tmp_path / "synthetic-weights.pt"
    weights.write_bytes(b"fixture only, never load with real torch")
    return Settings(stt_provider="whisper", stt_model="configured-test-model", stt_model_path=str(weights))


def test_missing_weights_fails_before_loading_or_downloading() -> None:
    calls = []
    def loader(path: str, device: str) -> object:
        calls.append(path)
        raise AssertionError("must not be called")
    provider = LocalWhisper(Settings(stt_provider="whisper"), loader=loader)
    try:
        with pytest.raises(DomainError, match="不会自动下载"):
            provider.load()
        assert calls == []
    finally:
        provider.close()


def test_reuses_existing_file_model_and_decodes_in_memory(tmp_path: Path) -> None:
    settings = configuration(tmp_path)
    loads: list[tuple[str, str]] = []
    received: list[object] = []
    options: list[dict[str, object]] = []
    samples = object()
    class Model:
        def transcribe(self, content: object, **kwargs: object) -> object:
            received.append(content)
            options.append(kwargs)
            return {"text": "  合成中文转写  ", "language": "zh", "segments": []}
    def loader(path: str, device: str) -> Model:
        loads.append((path, device))
        return Model()
    provider = LocalWhisper(settings, loader=loader, decoder=lambda _wav: samples)
    try:
        provider.load()
        assert provider.transcribe(audio()).text == "合成中文转写"
        assert provider.transcribe(audio()).text == "合成中文转写"
        assert loads == [(str(Path(settings.stt_model_path).resolve()), "cpu")]
        assert received == [samples, samples]
        assert all(o["language"] == "zh" and o["fp16"] is False and o["verbose"] is None for o in options)
        assert all("initial_prompt" not in option for option in options)
        assert list(tmp_path.iterdir()) == [Path(settings.stt_model_path)]
    finally:
        provider.close()


def test_initial_prompt_from_env_is_passed_to_whisper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = "以下是普通话技术面试回答，请使用简体中文和简体标点。"
    monkeypatch.setattr("interviewer.settings.ROOT", tmp_path)
    monkeypatch.setenv("DB_DRIVER", "sqlite")
    monkeypatch.setenv("STT_INITIAL_PROMPT", prompt)
    settings = Settings.from_env()
    settings.stt_model_path = configuration(tmp_path).stt_model_path
    settings.stt_model_sha256 = ""

    class Model:
        def transcribe(self, _content: object, **options: object) -> object:
            assert options["initial_prompt"] == prompt
            return {"text": "合成中文结果"}

    provider = LocalWhisper(settings, loader=lambda *_args: Model(), decoder=lambda wav: wav)
    try:
        assert provider.transcribe(audio()).text == "合成中文结果"
    finally:
        provider.close()


def test_weight_hash_mismatch_rejects_before_loader(tmp_path: Path) -> None:
    settings = configuration(tmp_path)
    settings.stt_model_sha256 = "0" * 64
    provider = LocalWhisper(settings, loader=lambda *_args: pytest.fail("must not load"))
    try:
        with pytest.raises(DomainError, match="校验失败"):
            provider.load()
    finally:
        provider.close()


@pytest.mark.parametrize("result", [{"text": "   "}, {"text": "x" * 4001}, {"text": 12}, {"unexpected": "no text"}])
def test_invalid_output_never_becomes_fabricated_text(tmp_path: Path, result: object) -> None:
    class Model:
        def transcribe(self, _content: object, **_kwargs: object) -> object:
            return result
    provider = LocalWhisper(configuration(tmp_path), loader=lambda *_args: Model(), decoder=lambda wav: wav)
    try:
        with pytest.raises(DomainError) as error:
            provider.transcribe(audio())
        assert error.value.code == "SPEECH_UNAVAILABLE"
    finally:
        provider.close()


def test_timeout_keeps_running_inference_bounded(tmp_path: Path) -> None:
    settings = configuration(tmp_path)
    settings.stt_timeout = 0.1
    started, release = threading.Event(), threading.Event()
    calls = []
    class Model:
        def transcribe(self, _content: object, **_kwargs: object) -> object:
            calls.append(1)
            started.set()
            release.wait(2)
            return {"text": "合成结果"}
    provider = LocalWhisper(settings, loader=lambda *_args: Model(), decoder=lambda wav: wav)
    try:
        with pytest.raises(DomainError, match="超时"):
            provider.transcribe(audio())
        assert started.is_set()
        with pytest.raises(DomainError, match="繁忙"):
            provider.transcribe(audio())
        assert len(calls) == 1
    finally:
        release.set()
        provider.close()


def test_changed_model_configuration_requires_restart(tmp_path: Path) -> None:
    settings = configuration(tmp_path)
    class Model:
        def transcribe(self, _content: object, **_kwargs: object) -> object:
            return {"text": "合成结果"}
    provider = LocalWhisper(settings, loader=lambda *_args: Model())
    try:
        provider.load()
        settings.stt_device = "changed-device"
        with pytest.raises(DomainError, match="重启"):
            provider.load()
    finally:
        provider.close()


def test_startup_fails_if_selected_local_weights_are_missing() -> None:
    app = create_app(Settings(sqlite_path=":memory:", stt_provider="whisper", stt_model="fixture"))
    with pytest.raises(DomainError, match="不会自动下载"), TestClient(app):
        pytest.fail("startup must fail before serving requests")


def test_whisper_http_preview_preserves_consent_and_manual_submission(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    created, _ = invitation(client, mode="voice")
    identity = str(created["interviewId"])
    headers = {"Authorization": "Bearer " + str(created["inviteToken"]), "Idempotency-Key": "local-preview"}
    service = cast(Service, client.app.state.service)
    service.settings.stt_provider = "whisper"
    calls: list[bytes] = []
    def transcribe(content: bytes) -> SpeechOutput:
        calls.append(content)
        return SpeechOutput(text="合成中文结果，需要本人确认")
    monkeypatch.setattr(service.whisper, "transcribe", transcribe)
    upload = {"audio": ("answer.wav", audio(), "audio/wav")}
    assert client.post(f"/api/interviews/{identity}/transcribe", headers=headers, files=upload).status_code == 409
    assert calls == []
    state = json_object(client.get(f"/api/interviews/{identity}/state", headers=headers).json())
    assert state["speechServerEnabled"] is True
    assert client.post(f"/api/interviews/{identity}/consent", headers=headers,
                       json={"accepted": True, "consentVersion": state["consentVersion"]}).status_code == 200
    assert client.post(f"/api/interviews/{identity}/media", headers=headers,
                       json={"cameraActive": False, "microphoneActive": True, "reason": "check"}).status_code == 200
    assert client.post(f"/api/interviews/{identity}/start", headers=headers, json={}).status_code == 200
    for _ in range(2):
        result = client.post(f"/api/interviews/{identity}/transcribe", headers=headers, files=upload)
        assert result.status_code == 200, result.text
        assert result.json() == {"text": "合成中文结果，需要本人确认"}
    assert len(calls) == 1
    state = json_object(client.get(f"/api/interviews/{identity}/state", headers=headers).json())
    assert not [row for row in cast(list[dict[str, object]], state["turns"]) if row["role"] == "candidate"]
