from __future__ import annotations

import time
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from interviewer.contracts import json_object
from interviewer.feishu import (
    STATE_STORE,
    FakeFeishu,
    LiveFeishu,
    encrypt_event_for_tests,
)
from interviewer.main import create_app
from interviewer.settings import Settings

SECRET = "fixture-" * 8
VERIFY = "verify-token-fixture"
ENCRYPT = "encrypt-key-fixture"
IV = bytes(range(16))


def settings(**overrides: object) -> Settings:
    base = {
        "sqlite_path": ":memory:",
        "secret": SECRET,
        "admin_key": "fixture-admin",
        "recruiter_key": "fixture-recruiter",
        "feishu_app_id": "cli_fixture",
        "feishu_app_secret": "app-secret-fixture",
        "feishu_verification_token": VERIFY,
        "feishu_encrypt_key": "",
        "feishu_api_base_url": "https://open.feishu.cn",
        "feishu_oauth_redirect_uri": "https://example.invalid/feishu/callback",
        "feishu_recruiter_open_ids": "ou_recruiter",
        "feishu_admin_open_ids": "ou_admin",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def configured() -> Iterator[tuple[TestClient, FakeFeishu]]:
    app = create_app(settings())
    port = FakeFeishu(open_id="ou_recruiter")
    app.state.feishu = port
    with TestClient(app) as client:
        yield client, port


def issue_state(client: TestClient, *, expires_offset_ms: int = 60_000) -> str:
    auth = client.app.state.service.auth
    state = STATE_STORE.issue(auth)
    if expires_offset_ms == 60_000:
        return state
    nonce, _expires, _signature = state.split(".", 2)
    expires = int(time.time() * 1000) + expires_offset_ms
    payload = f"feishu-oauth-v1:{nonce}:{expires}"
    return f"{nonce}.{expires}.{auth.digest(payload)}"


def test_unconfigured_status_and_no_outbound() -> None:
    calls: list[httpx.Request] = []

    def track(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500, json={"code": 1})

    app = create_app(settings(feishu_app_id="", feishu_app_secret=""))
    # Even if a Live port is injected, unconfigured routes must fail before outbound I/O.
    app.state.feishu = LiveFeishu(
        settings(feishu_app_id="cli_x", feishu_app_secret="secret_x"),
        transport=httpx.MockTransport(track),
    )
    with TestClient(app) as client:
        status = client.get("/api/feishu/status")
        assert status.status_code == 200
        body = json_object(status.json())
        assert body["configured"] is False
        assert body["appId"] == ""
        callback = client.post("/api/feishu/oauth/callback", json={"code": "x", "state": "a.1.b"})
        assert callback.status_code == 400
        assert json_object(callback.json())["error"]["code"] == "FEISHU_NOT_CONFIGURED"
        events = client.post("/api/feishu/events", json={"type": "url_verification", "challenge": "c", "token": VERIFY})
        assert events.status_code == 400
        assert json_object(events.json())["error"]["code"] == "FEISHU_NOT_CONFIGURED"
    assert calls == []


def test_whitelist_hit_sets_cookie_and_audits(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, port = configured
    state = issue_state(client)
    response = client.post("/api/feishu/oauth/callback", json={"code": "auth-code", "state": state})
    assert response.status_code == 200
    assert response.json()["role"] == "recruiter"
    assert "aii_recruiter=" in response.headers.get("set-cookie", "")
    assert port.exchange_calls == 1
    with client.app.state.service.database.unit_of_work() as connection:
        from interviewer import database as db
        rows = db.rows(connection, db.audit_logs.select().where(db.audit_logs.c.action == "feishu.login"))
    assert len(rows) == 1
    meta = rows[0]["metadata"]
    assert meta["role"] == "recruiter"
    assert "openIdHash" in meta
    assert "ou_recruiter" not in str(meta)
    assert "auth-code" not in str(meta)


def test_whitelist_miss_forbidden(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, port = configured
    port.open_id = "ou_stranger"
    state = issue_state(client)
    response = client.post("/api/feishu/oauth/callback", json={"code": "auth-code", "state": state})
    assert response.status_code == 403
    assert json_object(response.json())["error"]["code"] == "FEISHU_ROLE_NOT_ALLOWED"
    assert "set-cookie" not in {key.lower() for key in response.headers.keys()} or "aii_" not in response.headers.get("set-cookie", "")
    assert port.exchange_calls == 1


def test_state_expired_skips_exchange(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, port = configured
    expired = issue_state(client, expires_offset_ms=-1_000)
    response = client.post("/api/feishu/oauth/callback", json={"code": "c", "state": expired})
    assert response.status_code == 400
    assert json_object(response.json())["error"]["code"] == "FEISHU_STATE_INVALID"
    assert port.exchange_calls == 0


def test_state_reuse_skips_second_exchange(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, port = configured
    state = issue_state(client)
    assert client.post("/api/feishu/oauth/callback", json={"code": "c", "state": state}).status_code == 200
    assert port.exchange_calls == 1
    replay = client.post("/api/feishu/oauth/callback", json={"code": "c", "state": state})
    assert replay.status_code == 400
    assert json_object(replay.json())["error"]["code"] == "FEISHU_STATE_INVALID"
    assert port.exchange_calls == 1


def test_state_bad_signature_skips_exchange(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, port = configured
    bad = issue_state(client) + "x"
    response = client.post("/api/feishu/oauth/callback", json={"code": "c", "state": bad})
    assert response.status_code == 400
    assert json_object(response.json())["error"]["code"] == "FEISHU_STATE_INVALID"
    assert port.exchange_calls == 0


def test_admin_whitelist_hit_sets_admin_cookie(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, port = configured
    port.open_id = "ou_admin"
    state = issue_state(client)
    response = client.post("/api/feishu/oauth/callback", json={"code": "auth-code", "state": state})
    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert "aii_admin=" in response.headers.get("set-cookie", "")


def test_events_url_verification_and_token() -> None:
    app = create_app(settings())
    app.state.feishu = FakeFeishu()
    with TestClient(app) as client:
        ok = client.post("/api/feishu/events", json={"type": "url_verification", "challenge": "ping-42", "token": VERIFY})
        assert ok.status_code == 200
        assert ok.json() == {"challenge": "ping-42"}
        bad = client.post("/api/feishu/events", json={"type": "url_verification", "challenge": "ping-42", "token": "wrong"})
        assert bad.status_code == 400
        assert json_object(bad.json())["error"]["code"] == "FEISHU_SIGNATURE_INVALID"


def test_events_encrypted_roundtrip_and_tamper() -> None:
    app = create_app(settings(feishu_encrypt_key=ENCRYPT))
    app.state.feishu = FakeFeishu()
    payload = {"type": "url_verification", "challenge": "enc-challenge", "token": VERIFY}
    encrypted = encrypt_event_for_tests(ENCRYPT, payload, IV)
    with TestClient(app) as client:
        ok = client.post("/api/feishu/events", json={"encrypt": encrypted})
        assert ok.status_code == 200
        assert ok.json() == {"challenge": "enc-challenge"}
        raw = bytearray(encrypted.encode())
        # Tamper one byte inside the base64 payload body.
        raw[-2] = (raw[-2] % 26) + 65
        bad = client.post("/api/feishu/events", json={"encrypt": raw.decode()})
        assert bad.status_code == 400
        assert json_object(bad.json())["error"]["code"] == "FEISHU_SIGNATURE_INVALID"


def test_upstream_failure_no_cookie(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, _port = configured
    calls: list[httpx.Request] = []

    def boom(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, json={"code": 1, "msg": "down"})

    client.app.state.feishu = LiveFeishu(settings(), transport=httpx.MockTransport(boom))
    state = issue_state(client)
    response = client.post("/api/feishu/oauth/callback", json={"code": "auth-code", "state": state})
    assert response.status_code == 502
    assert json_object(response.json())["error"]["code"] == "FEISHU_UPSTREAM_FAILED"
    assert "aii_recruiter" not in response.headers.get("set-cookie", "")
    assert len(calls) >= 1
