import asyncio
from collections.abc import AsyncIterator
from typing import cast

import pytest
from fastapi.testclient import TestClient

from conftest import invitation
from interviewer.contracts import json_object
from interviewer.errors import DomainError
from interviewer.main import create_app
from interviewer.service import Service
from interviewer.settings import Settings
from interviewer.tts import MAX_TTS_BYTES, EdgeTTS


def settings() -> Settings:
    return Settings(tts_provider="edge", tts_allow_external=True, tts_voice="synthetic-voice")


class Audio:
    async def stream(self) -> AsyncIterator[object]:
        yield {"type": "WordBoundary", "text": "ignored metadata"}
        yield {"type": "audio", "data": b"synthetic-mp3"}


@pytest.mark.parametrize("config", [Settings(), Settings(tts_provider="edge", tts_voice="fixture"),
                                   Settings(tts_provider="edge", tts_allow_external=True)])
def test_external_permission_and_voice_checked_before_factory(config: Settings) -> None:
    def never(*_args: object) -> Audio:
        pytest.fail("external service must not be invoked")
    with pytest.raises(DomainError, match="明确允许外网"):
        asyncio.run(EdgeTTS(config, never).synthesize("合成题目"))


def test_selected_edge_without_external_permission_fails_startup() -> None:
    app = create_app(Settings(sqlite_path=":memory:", tts_provider="edge", tts_voice="fixture"))
    with pytest.raises(DomainError, match="明确允许外网"), TestClient(app):
        pytest.fail("must fail before serving requests")


def test_stream_assembles_only_audio_and_uses_configured_parameters() -> None:
    config, received = settings(), []
    def factory(text: str, options: Settings) -> Audio:
        received.append((text, options.tts_voice, options.tts_rate, options.tts_timeout))
        return Audio()
    result = asyncio.run(EdgeTTS(config, factory).synthesize("合成题目"))
    assert result == b"synthetic-mp3"
    assert received == [("合成题目", config.tts_voice, config.tts_rate, config.tts_timeout)]


def test_library_adapter_passes_explicit_timeouts_without_requesting_voice_list(monkeypatch: pytest.MonkeyPatch) -> None:
    import interviewer.tts as module
    received: list[tuple[str, str, dict[str, object]]] = []
    class Library:
        def Communicate(self, text: str, voice: str, **options: object) -> Audio:
            received.append((text, voice, options))
            return Audio()
    monkeypatch.setattr(module, "version", lambda _name: module.EDGE_VERSION)
    monkeypatch.setattr(module.importlib, "import_module", lambda _name: Library())
    config = settings()
    assert asyncio.run(EdgeTTS(config).synthesize("合成题目")) == b"synthetic-mp3"
    assert received == [("合成题目", config.tts_voice, {"rate": config.tts_rate,
                         "connect_timeout": config.tts_connect_timeout, "receive_timeout": config.tts_timeout})]


@pytest.mark.parametrize("chunks", [[], [{"type": "audio", "data": "not bytes"}],
                                  [{"type": "audio", "data": b"x" * (MAX_TTS_BYTES + 1)}],
                                  [{"type": "audio", "data": b"x" * MAX_TTS_BYTES}, {"type": "audio", "data": b"x"}]])
def test_invalid_audio_never_becomes_success(chunks: list[object]) -> None:
    class Invalid:
        async def stream(self) -> AsyncIterator[object]:
            for row in chunks:
                yield row
    with pytest.raises(DomainError, match="失败或超时"):
        asyncio.run(EdgeTTS(settings(), lambda *_args: Invalid()).synthesize("合成题目"))


def test_upstream_exception_is_sanitized_and_does_not_fallback() -> None:
    def failing(*_args: object) -> Audio:
        raise RuntimeError("sensitive upstream diagnostics")
    with pytest.raises(DomainError) as error:
        asyncio.run(EdgeTTS(settings(), failing).synthesize("合成题目"))
    assert "sensitive" not in str(error.value)
    assert error.value.code == "SPEECH_UNAVAILABLE"


def test_concurrency_is_bounded_and_cancellation_releases_slot() -> None:
    async def exercise() -> None:
        started = asyncio.Event()
        class Waiting:
            async def stream(self) -> AsyncIterator[object]:
                started.set()
                await asyncio.Event().wait()
                yield {"type": "audio", "data": b"unreachable"}
        config = settings()
        config.tts_max_concurrency = 1
        provider = EdgeTTS(config, lambda *_args: Waiting())
        task = asyncio.create_task(provider.synthesize("合成题目"))
        await started.wait()
        with pytest.raises(DomainError, match="繁忙"):
            await provider.synthesize("另一题目")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        provider._factory = lambda *_args: Audio()
        assert await provider.synthesize("重试题目") == b"synthetic-mp3"
    asyncio.run(exercise())


def test_timeout_is_explicit() -> None:
    class Waiting:
        async def stream(self) -> AsyncIterator[object]:
            await asyncio.sleep(2)
            yield {"type": "audio", "data": b"too late"}
    config = settings()
    config.tts_timeout = 1
    with pytest.raises(DomainError, match="失败或超时"):
        asyncio.run(EdgeTTS(config, lambda *_args: Waiting()).synthesize("合成题目"))


def test_http_only_reads_current_question_after_versioned_consent(client: TestClient) -> None:
    service = cast(Service, client.app.state.service)
    service.settings.tts_provider, service.settings.tts_allow_external, service.settings.tts_voice = "edge", True, "fixture"
    received: list[str] = []
    def factory(text: str, _config: Settings) -> Audio:
        received.append(text)
        return Audio()
    service.tts = EdgeTTS(service.settings, factory)
    created, _ = invitation(client, mode="voice")
    identity = str(created["interviewId"])
    headers = {"Authorization": "Bearer " + str(created["inviteToken"])}
    url = f"/api/interviews/{identity}/tts?questionSeq=1&turnSeq=1"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=headers).status_code == 409
    assert received == []
    state = client.get(f"/api/interviews/{identity}/state", headers=headers).json()
    assert state["consentVersion"].endswith("-edge-question-v1")
    assert "微软Edge在线" in state["consentText"] and state["ttsServerEnabled"] is True
    assert client.post(f"/api/interviews/{identity}/consent", headers=headers,
                       json={"accepted": True, "consentVersion": state["consentVersion"]}).status_code == 200
    assert client.post(f"/api/interviews/{identity}/media", headers=headers,
                       json={"cameraActive": False, "microphoneActive": True, "reason": "check"}).status_code == 200
    assert client.post(f"/api/interviews/{identity}/start", headers=headers, json={}).status_code == 200
    state = client.get(f"/api/interviews/{identity}/state", headers=headers).json()
    turn = next(turn for turn in reversed(state["turns"]) if turn["role"] == "interviewer")
    url = f"/api/interviews/{identity}/tts?questionSeq={state['questionSeq']}&turnSeq={turn['seq']}"
    response = client.get(url + "&text=arbitrary-candidate-text", headers=headers)
    assert response.status_code == 200, response.text
    assert response.content == b"synthetic-mp3"
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["cache-control"] == "no-store"
    assert received == [state["currentQuestion"]["text"]]
    assert client.get(url.replace("questionSeq=1", "questionSeq=999"), headers=headers).status_code == 409
    assert len(received) == 1
    assert client.post(f"/api/interviews/{identity}/pause", headers=headers, json={"paused": True}).status_code == 200
    assert client.get(url, headers=headers).status_code == 409
    assert len(received) == 1


def test_changing_to_external_processing_does_not_reuse_old_consent(client: TestClient) -> None:
    created, _ = invitation(client, mode="voice")
    headers = {"Authorization": "Bearer " + str(created["inviteToken"])}
    identity = str(created["interviewId"])
    service = cast(Service, client.app.state.service)
    state = client.get(f"/api/interviews/{identity}/state", headers=headers).json()
    assert client.post(f"/api/interviews/{identity}/consent", headers=headers,
                       json={"accepted": True, "consentVersion": state["consentVersion"]}).status_code == 200
    assert client.post(f"/api/interviews/{identity}/media", headers=headers,
                       json={"cameraActive": False, "microphoneActive": True, "reason": "check"}).status_code == 200
    assert client.post(f"/api/interviews/{identity}/start", headers=headers, json={}).status_code == 200
    service.settings.tts_provider, service.settings.tts_allow_external, service.settings.tts_voice = "edge", True, "fixture"
    service.tts = EdgeTTS(service.settings, lambda *_args: pytest.fail("old consent must never permit external processing"))
    state = json_object(client.get(f"/api/interviews/{identity}/state", headers=headers).json())
    turn = next(turn for turn in reversed(cast(list[dict[str, object]], state["turns"])) if turn["role"] == "interviewer")
    result = client.get(f"/api/interviews/{identity}/tts?questionSeq={state['questionSeq']}&turnSeq={turn['seq']}", headers=headers)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "CONSENT_REQUIRED"
