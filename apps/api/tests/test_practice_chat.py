import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from interviewer.chat_api import CHAT_PATH, SESSION_PATH, WEB_ORIGIN
from interviewer.contracts import SpeechOutput
from interviewer.errors import DomainError
from interviewer.llm_service import FAKE_QUESTIONS, LLMService
from interviewer.local_whisper import LocalWhisper
from interviewer.main import create_app
from interviewer.settings import Settings
from test_local_whisper import audio


def start(client: TestClient) -> dict[str, str]:
    headers = {"Authorization": "Bearer " + uuid4().hex + uuid4().hex, "Origin": WEB_ORIGIN}
    info = client.get(CHAT_PATH).json()
    response = client.put(SESSION_PATH, headers=headers, json={"accepted": True, "consent_version": info["consent_version"]})
    assert response.status_code == 200, response.text
    return headers


def test_text_context_idempotency_and_erasure(client: TestClient) -> None:
    headers = start(client)
    form = {"text": (None, "我负责设计缓存，并验证命中率。")}
    keyed = {**headers, "Idempotency-Key": "round-1"}
    first = client.post(CHAT_PATH, headers=keyed, files=form)
    assert first.status_code == 200, first.text
    assert first.json() == {"user_text": form["text"][1], "ai_reply": FAKE_QUESTIONS[0]}
    assert client.post(CHAT_PATH, headers=keyed, files=form).json() == first.json()
    assert client.post(CHAT_PATH, headers=keyed, files={"text": (None, "不同回答")}).status_code == 409
    second = client.post(CHAT_PATH, headers=headers, files={"text": (None, "我记录了延迟分位数。")})
    assert second.status_code == 200, second.text
    assert second.json()["ai_reply"] == FAKE_QUESTIONS[1]
    assert client.get(SESSION_PATH, headers=headers).json() == {"turns": [first.json(), second.json()]}
    assert client.delete(SESSION_PATH, headers=headers).status_code == 204
    assert client.delete(SESSION_PATH, headers=headers).status_code == 204
    assert client.get(SESSION_PATH, headers=headers).status_code == 401


def test_wrong_consent_version_and_missing_consent_do_not_read_upload(client: TestClient) -> None:
    token = b"Bearer " + b"a" * 64
    response = client.put(SESSION_PATH, headers={"Authorization": token.decode()},
                          json={"accepted": True, "consent_version": "outdated"})
    assert response.status_code == 409
    read_count = 0
    sent = []

    async def receive() -> dict[str, object]:
        nonlocal read_count
        read_count += 1
        return {"type": "http.request", "body": b"unconsented material", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    asyncio.run(client.app({"type": "http", "method": "POST", "path": CHAT_PATH, "root_path": "",
                            "scheme": "http", "headers": [(b"authorization", token)], "query_string": b"",
                            "server": ("testserver", 80), "client": ("testclient", 0)}, receive, send))
    assert read_count == 0
    assert sent[0]["status"] == 401


def test_audio_uses_shared_whisper_and_failure_does_not_commit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    client.app.state.service.settings.stt_provider = "whisper"
    headers = start(client)
    calls: list[bytes] = []

    def transcribe(_self: LocalWhisper, content: bytes) -> SpeechOutput:
        calls.append(content)
        return SpeechOutput(text="我负责测试数据管道。")

    def fail(_self: LLMService, _messages: list[dict[str, str]]) -> str:
        raise DomainError("LLM_PROVIDER_UNAVAILABLE", "fixture")

    monkeypatch.setattr(LocalWhisper, "transcribe", transcribe)
    file = {"file": ("fixture.wav", audio(), "audio/wav")}
    with monkeypatch.context() as failure:
        failure.setattr(LLMService, "chat", fail)
        assert client.post(CHAT_PATH, headers=headers, files=file).status_code == 502
        assert client.get(SESSION_PATH, headers=headers).json() == {"turns": []}
    keyed = {**headers, "Idempotency-Key": "audio-1"}
    response = client.post(CHAT_PATH, headers=keyed, files=file)
    assert response.status_code == 200, response.text
    assert response.json() == {"user_text": "我负责测试数据管道。", "ai_reply": FAKE_QUESTIONS[0]}
    assert client.post(CHAT_PATH, headers=keyed, files=file).json() == response.json()
    assert calls == [audio(), audio()]


def test_validated_form_and_exact_cors_origin(client: TestClient) -> None:
    headers = start(client)
    file = ("fixture.wav", audio(), "audio/wav")
    assert client.post(CHAT_PATH, headers=headers, files={"file": file, "text": (None, "两种")}).status_code == 400
    assert client.post(CHAT_PATH, headers=headers, files={"text": (None, " ")}).status_code == 400
    assert client.post(CHAT_PATH, headers=headers, files={"text": (None, "长" * 4001)}).status_code == 400
    assert client.post(CHAT_PATH, headers=headers, files={"file": file}).status_code == 503
    assert client.get(SESSION_PATH, headers=headers).json() == {"turns": []}
    preflight = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,idempotency-key"}
    response = client.options(CHAT_PATH, headers={**preflight, "Origin": WEB_ORIGIN})
    assert response.status_code == 200 and response.headers["access-control-allow-origin"] == WEB_ORIGIN
    other = "http://untrusted.example:5173"
    response = client.options(CHAT_PATH, headers={**preflight, "Origin": other})
    assert response.status_code == 400 and "access-control-allow-origin" not in response.headers
    assert client.post(CHAT_PATH, headers={**headers, "Origin": other}, files={"text": (None, "回答")}).status_code == 403


def test_practice_history_survives_restart_and_isolated_from_other_tokens(tmp_path: Path) -> None:
    settings = Settings(sqlite_path=str(tmp_path / "practice.sqlite3"))
    with TestClient(create_app(settings)) as client:
        headers = start(client)
        response = client.post(CHAT_PATH, headers=headers, files={"text": (None, "我写了一个小工具。")})
        assert response.status_code == 200, response.text
        answer = response.json()
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(SESSION_PATH, headers=headers).json() == {"turns": [answer]}
        other = start(restarted)
        assert restarted.get(SESSION_PATH, headers=other).json() == {"turns": []}
