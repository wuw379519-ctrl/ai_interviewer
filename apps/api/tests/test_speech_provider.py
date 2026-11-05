import io
import json
import wave
from typing import cast
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from interviewer.contracts import CompetencySet, json_object
from interviewer.domain import fixture_competencies
from interviewer.errors import DomainError
from interviewer.provider import Provider
from interviewer.service import Service
from interviewer.settings import Settings
from interviewer.speech import MAX_AUDIO_BYTES, validate_wave
from conftest import invitation


def wave_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\0\0" * 1600)
    return output.getvalue()


@pytest.mark.parametrize("content", [b"video-container", b"RIFF" + b"\0" * 50, b"x" * (MAX_AUDIO_BYTES + 1)],
                         ids=["video-container", "malformed-riff", "over-audio-byte-limit"])
def test_rejects_video_malformed_and_oversized_audio(content: bytes) -> None:
    with pytest.raises(DomainError):
        validate_wave(content)
    validate_wave(wave_bytes())


def test_in_memory_preview_requires_consent_and_is_not_an_answer(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    created, person = invitation(client, mode="voice", camera=True)
    identity = str(created["interviewId"])
    headers = {"Authorization": "Bearer " + str(created["inviteToken"]), "Idempotency-Key": str(uuid4())}
    file = {"audio": ("answer.wav", wave_bytes(), "audio/wav")}
    assert client.post(f"/api/interviews/{identity}/transcribe", headers=headers, files=file).status_code == 409
    state = json_object(client.get(f"/api/interviews/{identity}/state", headers=headers).json())
    client.post(f"/api/interviews/{identity}/consent", headers=headers,
                json={"accepted": True, "consentVersion": state["consentVersion"]})
    assert client.post(f"/api/interviews/{identity}/start", headers=headers, json={}).status_code == 409
    assert client.post(f"/api/interviews/{identity}/media", headers=headers,
                       json={"cameraActive": True, "microphoneActive": True, "reason": "check"}).status_code == 200
    assert client.post(f"/api/interviews/{identity}/start", headers={"Authorization": headers["Authorization"]}, json={}).status_code == 200
    service = cast(Service, client.app.state.service)
    service.settings.stt_base_url, service.settings.stt_model = "http://synthetic-stt.invalid/v1", "fixture"
    calls = 0
    original_client = httpx.Client

    class Gateway:
        def __enter__(self) -> "Gateway":
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def post(self, *_args: object, **_kwargs: object) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"text": "合成转写预览，需要本人核对后才提交"}, request=httpx.Request("POST", "http://synthetic.invalid"))
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: Gateway())
    response = client.post(f"/api/interviews/{identity}/transcribe", headers=headers, files=file)
    assert response.status_code == 200, response.text
    assert client.post(f"/api/interviews/{identity}/transcribe", headers=headers, files=file).status_code == 200
    assert calls == 1
    state = json_object(client.get(f"/api/interviews/{identity}/state", headers=headers).json())
    assert not [row for row in cast(list[dict[str, object]], state["turns"]) if row["role"] == "candidate"]
    extra = client.post(f"/api/interviews/{identity}/transcribe", headers=headers, files={**file, "video": ("video.mp4", b"invalid", "video/mp4")})
    assert extra.status_code == 400
    monkeypatch.setattr(httpx, "Client", original_client)
    client.post("/api/admin/login", json={})
    assert client.request("DELETE", f"/api/candidates/{person['id']}", json={"confirmCandidateId": person["id"], "reason": "合成语音预览删除验证"}).status_code == 200
    assert not service.speech_cache


def test_text_fallback_keeps_required_camera_and_heartbeat_expiry(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    created, _ = invitation(client, mode="voice", camera=True)
    identity, headers = str(created["interviewId"]), {"Authorization": "Bearer " + str(created["inviteToken"])}
    state = json_object(client.get(f"/api/interviews/{identity}/state", headers=headers).json())
    client.post(f"/api/interviews/{identity}/consent", headers=headers, json={"accepted": True, "consentVersion": state["consentVersion"]})
    client.post(f"/api/interviews/{identity}/media", headers=headers, json={"cameraActive": False, "microphoneActive": False, "reason": "check", "textFallback": True})
    assert client.post(f"/api/interviews/{identity}/start", headers=headers, json={}).status_code == 409
    client.post(f"/api/interviews/{identity}/media", headers=headers, json={"cameraActive": True, "microphoneActive": False, "reason": "check", "textFallback": True})
    assert client.post(f"/api/interviews/{identity}/start", headers=headers, json={}).status_code == 200
    from interviewer import database as db
    from datetime import timedelta
    current = db.now()
    monkeypatch.setattr(db, "now", lambda: current + timedelta(seconds=31))
    after = json_object(client.get(f"/api/interviews/{identity}/state", headers=headers).json())
    assert after["pausedAt"] is not None and after["questionSeq"] == 1
    assert after["cameraActive"] is False


def test_structured_gateway_retries_once_and_uses_validated_relaxed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = Provider(Settings(provider="internal", llm_base_url="http://synthetic.invalid/v1", llm_model="fixture"))
    expected = fixture_competencies(False)
    calls = 0

    def post(_self: object, *_args: object, **_kwargs: object) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = "invalid-json" if calls == 1 else "```json\n" + expected.model_dump_json(by_alias=True) + "\n```"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 7, "completion_tokens": 5}}, request=httpx.Request("POST", "http://synthetic.invalid"))
    monkeypatch.setattr(httpx.Client, "post", post)
    result = provider.structured("competency_extraction", [{"role": "user", "content": "synthetic"}], CompetencySet, expected.payload())
    assert calls == 2 and result.data == expected and result.usage["totalTokens"] == 24


def test_model_prompt_leak_is_rejected_even_if_json_is_well_formed(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = Provider(Settings(provider="internal", llm_base_url="http://synthetic.invalid/v1", llm_model="fixture"))
    data = fixture_competencies(False).payload()
    cast(list[dict[str, object]], data["competencies"])[0]["name"] = "AII_SENTINEL_DO_NOT_REVEAL"

    def post(_self: object, *_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(data, ensure_ascii=False)}}]}, request=httpx.Request("POST", "http://synthetic.invalid"))
    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(DomainError):
        provider.structured("competency_extraction", [], CompetencySet, data)
