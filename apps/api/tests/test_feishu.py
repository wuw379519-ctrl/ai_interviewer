from __future__ import annotations

import json
import time
from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from interviewer import database as db
from interviewer.contracts import json_object
from interviewer.feishu import (
    OAUTH_NONCE_COOKIE,
    STATE_STORE,
    FakeFeishu,
    LiveFeishu,
    encrypt_event_for_tests,
    state_nonce,
)
from interviewer.main import create_app
from interviewer.settings import Settings

SECRET = "fixture-" * 8
VERIFY = "verify-token-fixture"
ENCRYPT = "encrypt-key-fixture"
IV = bytes(range(16))
REDIRECT = "https://example.invalid/feishu/callback"


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
        "feishu_oauth_redirect_uri": REDIRECT,
        "feishu_scopes": "contact:user.id:readonly",
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


def post_callback(client: TestClient, code: str, state: str, *, nonce: str | None = None) -> httpx.Response:
    value = state_nonce(state) if nonce is None else nonce
    client.cookies.set(OAUTH_NONCE_COOKIE, value)
    return client.post("/api/feishu/oauth/callback", json={"code": code, "state": state})


def test_unconfigured_status_and_no_outbound() -> None:
    calls: list[httpx.Request] = []

    def track(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500, json={"code": 1})

    app = create_app(settings(feishu_app_id="", feishu_app_secret=""))
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
        assert client.get("/api/feishu/oauth/start").status_code == 400
        callback = post_callback(client, "x", "a.1.b")
        assert callback.status_code == 400
        assert json_object(callback.json())["error"]["code"] == "FEISHU_NOT_CONFIGURED"
        events = client.post("/api/feishu/events", json={"type": "url_verification", "challenge": "c", "token": VERIFY})
        assert events.status_code == 400
        assert json_object(events.json())["error"]["code"] == "FEISHU_NOT_CONFIGURED"
    assert calls == []


def test_whitelist_hit_sets_cookie_and_audits(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, port = configured
    state = issue_state(client)
    response = post_callback(client, "auth-code", state)
    assert response.status_code == 200
    assert response.json()["role"] == "recruiter"
    assert "aii_recruiter=" in response.headers.get("set-cookie", "")
    assert port.exchange_calls == 1
    with client.app.state.service.database.unit_of_work() as connection:
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
    response = post_callback(client, "auth-code", state)
    assert response.status_code == 403
    assert json_object(response.json())["error"]["code"] == "FEISHU_ROLE_NOT_ALLOWED"
    assert "aii_recruiter" not in response.headers.get("set-cookie", "")
    assert port.exchange_calls == 1


def test_state_expired_skips_exchange(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, port = configured
    expired = issue_state(client, expires_offset_ms=-1_000)
    response = post_callback(client, "c", expired)
    assert response.status_code == 400
    assert json_object(response.json())["error"]["code"] == "FEISHU_STATE_INVALID"
    assert port.exchange_calls == 0


def test_state_reuse_skips_second_exchange(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, port = configured
    state = issue_state(client)
    assert post_callback(client, "c", state).status_code == 200
    assert port.exchange_calls == 1
    replay = post_callback(client, "c", state)
    assert replay.status_code == 400
    assert json_object(replay.json())["error"]["code"] == "FEISHU_STATE_INVALID"
    assert port.exchange_calls == 1


def test_state_bad_signature_skips_exchange(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, port = configured
    bad = issue_state(client) + "x"
    response = post_callback(client, "c", bad)
    assert response.status_code == 400
    assert json_object(response.json())["error"]["code"] == "FEISHU_STATE_INVALID"
    assert port.exchange_calls == 0


def test_admin_whitelist_hit_sets_admin_cookie(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, port = configured
    port.open_id = "ou_admin"
    state = issue_state(client)
    response = post_callback(client, "auth-code", state)
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
    response = post_callback(client, "auth-code", state)
    assert response.status_code == 502
    assert json_object(response.json())["error"]["code"] == "FEISHU_UPSTREAM_FAILED"
    assert "aii_recruiter" not in response.headers.get("set-cookie", "")
    assert len(calls) >= 1


def test_oauth_start_uses_separate_rate_limit_bucket(configured: tuple[TestClient, FakeFeishu]) -> None:
    _client, _port = configured
    # Non-demo apps use login bucket 10/min; start uses feishu:start 60/min and must stay independent.
    app = create_app(settings(demo=False, environment="production", secret=SECRET))
    app.state.feishu = FakeFeishu()
    with TestClient(app) as limited:
        for _ in range(11):
            limited.post("/api/auth/login", json={"username": "nope", "password": "nope"})
        start = limited.get("/api/feishu/oauth/start", follow_redirects=False)
        assert start.status_code == 302


def test_oauth_callback_shares_login_rate_limit_bucket() -> None:
    app = create_app(settings(demo=False, environment="production", secret=SECRET))
    port = FakeFeishu(open_id="ou_recruiter")
    app.state.feishu = port
    with TestClient(app) as limited:
        for _ in range(10):
            limited.post("/api/auth/login", json={"username": "nope", "password": "nope"})
        state = issue_state(limited)
        blocked = post_callback(limited, "auth-code", state)
        assert blocked.status_code == 429
        assert port.exchange_calls == 0


def test_oauth_start_redirect_and_nonce_cookie(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, _port = configured
    response = client.get("/api/feishu/oauth/start", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.feishu.cn"
    assert parsed.path.endswith("/open-apis/authen/v1/authorize")
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["cli_fixture"]
    assert query["redirect_uri"] == [REDIRECT]
    assert query["scope"] == ["contact:user.id:readonly"]
    assert "state" in query
    assert OAUTH_NONCE_COOKIE in response.headers.get("set-cookie", "")
    assert state_nonce(query["state"][0]) in response.headers.get("set-cookie", "")


def test_callback_requires_matching_nonce_cookie(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, port = configured
    state = issue_state(client)
    missing = client.post("/api/feishu/oauth/callback", json={"code": "c", "state": state})
    assert missing.status_code == 400
    assert json_object(missing.json())["error"]["code"] == "FEISHU_STATE_INVALID"
    assert port.exchange_calls == 0

    state2 = issue_state(client)
    mismatched = post_callback(client, "c", state2, nonce="not-the-nonce")
    assert mismatched.status_code == 400
    assert json_object(mismatched.json())["error"]["code"] == "FEISHU_STATE_INVALID"
    assert port.exchange_calls == 0


def test_events_empty_verification_token_not_configured() -> None:
    app = create_app(settings(feishu_verification_token=""))
    app.state.feishu = FakeFeishu()
    with TestClient(app) as client:
        response = client.post("/api/feishu/events", json={"type": "url_verification", "challenge": "c", "token": ""})
        assert response.status_code == 400
        assert json_object(response.json())["error"]["code"] == "FEISHU_NOT_CONFIGURED"


def test_unknown_events_do_not_write_audit_rows() -> None:
    app = create_app(settings())
    app.state.feishu = FakeFeishu()
    with TestClient(app) as client:
        with client.app.state.service.database.unit_of_work() as connection:
            before = len(db.rows(connection, db.audit_logs.select()))
        for index in range(5):
            response = client.post(
                "/api/feishu/events",
                json={"type": f"im.message.receive_v1.{index}", "token": VERIFY},
            )
            assert response.status_code == 200
        with client.app.state.service.database.unit_of_work() as connection:
            after = len(db.rows(connection, db.audit_logs.select()))
        assert after == before


def test_live_exchange_v2_happy_path(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, _port = configured
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path.endswith("/open-apis/authen/v2/oauth/token")
        assert "authorization" not in {key.lower() for key in request.headers.keys()}
        body = json.loads(request.content.decode())
        assert body["redirect_uri"] == REDIRECT
        assert body["client_id"] == "cli_fixture"
        assert body["grant_type"] == "authorization_code"
        return httpx.Response(200, json={"code": 0, "open_id": "ou_recruiter"})

    client.app.state.feishu = LiveFeishu(settings(), transport=httpx.MockTransport(respond))
    state = issue_state(client)
    response = post_callback(client, "auth-code", state)
    assert response.status_code == 200
    assert "aii_recruiter=" in response.headers.get("set-cookie", "")
    assert len(calls) == 1


def test_live_exchange_business_error_code(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, _port = configured

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 20071, "msg": "code expired"})

    client.app.state.feishu = LiveFeishu(settings(), transport=httpx.MockTransport(respond))
    state = issue_state(client)
    response = post_callback(client, "auth-code", state)
    assert response.status_code == 502
    assert json_object(response.json())["error"]["code"] == "FEISHU_UPSTREAM_FAILED"
    assert "aii_recruiter" not in response.headers.get("set-cookie", "")


def test_live_tenant_token_refresh_with_clock() -> None:
    calls: list[str] = []
    tokens = iter(["token-one", "token-two"])

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": next(tokens), "expire": 1})
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "m1"}})

    clock = {"now": 1000.0}

    def monotonic() -> float:
        return clock["now"]

    live = LiveFeishu(settings(), transport=httpx.MockTransport(respond), clock=monotonic)
    assert live.tenant_access_token() == "token-one"
    clock["now"] = 1061.0  # past expire(1) with 60s skew
    assert live.tenant_access_token() == "token-two"
    assert sum(1 for path in calls if path.endswith("/tenant_access_token/internal")) == 2


def test_oauth_start_omits_scope_when_empty(configured: tuple[TestClient, FakeFeishu]) -> None:
    app = create_app(settings(feishu_scopes=""))
    app.state.feishu = FakeFeishu()
    with TestClient(app) as client:
        response = client.get("/api/feishu/oauth/start", follow_redirects=False)
        assert response.status_code == 302
        query = parse_qs(urlparse(response.headers["location"]).query)
        assert "scope" not in query


def test_live_exchange_non_numeric_code_is_upstream_failed(configured: tuple[TestClient, FakeFeishu]) -> None:
    client, _port = configured

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "not-a-number", "msg": "bad"})

    client.app.state.feishu = LiveFeishu(settings(), transport=httpx.MockTransport(respond))
    state = issue_state(client)
    response = post_callback(client, "auth-code", state)
    assert response.status_code == 502
    assert json_object(response.json())["error"]["code"] == "FEISHU_UPSTREAM_FAILED"


def test_live_send_text_uses_tenant_token() -> None:
    headers_seen: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "tenant-xyz", "expire": 7200})
        headers_seen.append(request.headers.get("Authorization", ""))
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "m1"}})

    live = LiveFeishu(settings(), transport=httpx.MockTransport(respond))
    live.send_text("ou_recruiter", "interview status only")
    assert headers_seen == ["Bearer tenant-xyz"]
