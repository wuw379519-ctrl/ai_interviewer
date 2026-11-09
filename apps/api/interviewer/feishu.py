from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Protocol
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .auth import Auth
from .contracts import Object
from .errors import DomainError
from .settings import Settings

OAUTH_STATE_PREFIX = "feishu-oauth-v1"
OAUTH_STATE_TTL_MS = 8 * 60 * 1000
OAUTH_STATE_CAP = 1000
TOKEN_SKEW_SEC = 60
REQUEST_TIMEOUT_SEC = 5.0
FEISHU_AUTHORIZE_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
OAUTH_NONCE_COOKIE = "feishu_oauth_nonce"


def _split_ids(value: str) -> set[str]:
    return {part.strip() for part in value.split(",") if part.strip()}


def feishu_configured(settings: Settings) -> bool:
    return bool(settings.feishu_app_id and settings.feishu_app_secret)


def require_feishu_configured(settings: Settings) -> None:
    if not feishu_configured(settings):
        raise DomainError("FEISHU_NOT_CONFIGURED", "飞书应用未配置")


def open_id_fingerprint(open_id: str) -> str:
    return hashlib.sha256(open_id.encode()).hexdigest()[:8]


def public_status(settings: Settings) -> Object:
    configured = feishu_configured(settings)
    login_enabled = bool(
        configured and settings.feishu_oauth_redirect_uri
        and (_split_ids(settings.feishu_recruiter_open_ids) or _split_ids(settings.feishu_admin_open_ids))
    )
    return {
        "configured": configured,
        "appId": settings.feishu_app_id if configured else "",
        "oauthRedirectUri": settings.feishu_oauth_redirect_uri if configured else "",
        "loginEnabled": login_enabled,
    }


def oauth_authorize_url(settings: Settings, state: str) -> str:
    params: dict[str, str] = {
        "client_id": settings.feishu_app_id,
        "redirect_uri": settings.feishu_oauth_redirect_uri,
        "state": state,
    }
    scopes = settings.feishu_scopes.strip()
    if scopes:
        params["scope"] = scopes
    return f"{FEISHU_AUTHORIZE_URL}?{urlencode(params)}"


def state_nonce(state: str) -> str:
    return state.split(".", 1)[0]


class FeishuPort(Protocol):
    def exchange_code(self, code: str) -> str: ...

    def send_text(self, open_id: str, text: str) -> None: ...


@dataclass
class FakeFeishu:
    open_id: str = "ou_fixture_recruiter"
    fail: bool = False
    delay_sec: float = 0
    exchange_calls: int = 0
    send_calls: list[tuple[str, str]] = field(default_factory=list)

    def exchange_code(self, code: str) -> str:
        self.exchange_calls += 1
        if self.delay_sec > 0:
            time.sleep(self.delay_sec)
        if self.fail:
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游调用失败")
        if not code.strip():
            raise DomainError("VALIDATION_FAILED", "缺少飞书授权码")
        return self.open_id

    def send_text(self, open_id: str, text: str) -> None:
        if self.fail:
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游调用失败")
        self.send_calls.append((open_id, text))


class LiveFeishu:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None,
                 clock: Callable[[], float] | None = None) -> None:
        require_feishu_configured(settings)
        self.settings = settings
        self.transport = transport
        self._clock = clock or time.monotonic
        self._token = ""
        self._token_expires = 0.0
        self._lock = threading.RLock()

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.settings.feishu_api_base_url.rstrip("/") + "/",
            timeout=REQUEST_TIMEOUT_SEC,
            follow_redirects=False,
            trust_env=False,
            transport=self.transport,
        )

    def _parse_business_code(self, payload: Object) -> int:
        raw = payload.get("code", 0)
        if raw is None:
            return 0
        if isinstance(raw, bool):
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游调用失败")
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str):
            try:
                return int(raw)
            except ValueError as error:
                raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游调用失败") from error
        raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游调用失败")

    def _request(self, method: str, path: str, *, json_body: Object | None = None,
                 headers: dict[str, str] | None = None) -> Object:
        try:
            with self._client() as client:
                response = client.request(method, path.lstrip("/"), json=json_body, headers=headers or {})
        except httpx.TimeoutException as error:
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游调用超时") from error
        except httpx.HTTPError as error:
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游调用失败") from error
        if response.status_code >= 500:
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游调用失败")
        try:
            payload = response.json()
        except ValueError as error:
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游响应无效") from error
        if not isinstance(payload, dict):
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游响应无效")
        if response.status_code >= 400 or self._parse_business_code(payload) != 0:
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游调用失败")
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游响应无效")
        return data

    def tenant_access_token(self) -> str:
        with self._lock:
            now = float(self._clock())
            if self._token and self._token_expires - TOKEN_SKEW_SEC > now:
                return self._token
            data = self._request(
                "POST",
                "open-apis/auth/v3/tenant_access_token/internal",
                json_body={"app_id": self.settings.feishu_app_id, "app_secret": self.settings.feishu_app_secret},
            )
            token = str(data.get("tenant_access_token") or "")
            expire_raw = data.get("expire")
            try:
                expire = int(expire_raw) if isinstance(expire_raw, int) else int(str(expire_raw))
            except (TypeError, ValueError):
                expire = 0
            if not token or expire <= 0:
                raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游调用失败")
            self._token = token
            self._token_expires = now + expire
            return token

    def exchange_code(self, code: str) -> str:
        try:
            with self._client() as client:
                response = client.request(
                    "POST",
                    "open-apis/authen/v2/oauth/token",
                    json={
                        "grant_type": "authorization_code",
                        "client_id": self.settings.feishu_app_id,
                        "client_secret": self.settings.feishu_app_secret,
                        "code": code,
                        "redirect_uri": self.settings.feishu_oauth_redirect_uri,
                    },
                    headers={},
                )
        except httpx.TimeoutException as error:
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游调用超时") from error
        except httpx.HTTPError as error:
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游调用失败") from error
        if response.status_code >= 500:
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游调用失败")
        try:
            payload = response.json()
        except ValueError as error:
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游响应无效") from error
        if not isinstance(payload, dict):
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游响应无效")
        if response.status_code >= 400 or self._parse_business_code(payload) != 0:
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游调用失败")
        nested = payload.get("data")
        open_id = str(payload.get("open_id") or (nested.get("open_id") if isinstance(nested, dict) else "") or "")
        if not open_id:
            raise DomainError("FEISHU_UPSTREAM_FAILED", "飞书上游调用失败")
        return open_id

    def send_text(self, open_id: str, text: str) -> None:
        token = self.tenant_access_token()
        self._request(
            "POST",
            "open-apis/im/v1/messages?receive_id_type=open_id",
            json_body={
                "receive_id": open_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        )


class OAuthStateStore:
    def __init__(self) -> None:
        self._used: dict[str, float] = {}
        self._lock = threading.RLock()

    def _prune(self, now: float) -> None:
        expired = [key for key, until in self._used.items() if until <= now]
        for key in expired:
            del self._used[key]
        if len(self._used) > OAUTH_STATE_CAP:
            ordered = sorted(self._used.items(), key=lambda item: item[1])
            for key, _ in ordered[: max(0, len(self._used) - OAUTH_STATE_CAP)]:
                del self._used[key]

    def issue(self, auth: Auth) -> str:
        if len(auth.secret) < 32:
            raise DomainError("UNAUTHORIZED", "服务未配置身份认证密钥")
        nonce = secrets.token_urlsafe(16)
        expires = int(time.time() * 1000) + OAUTH_STATE_TTL_MS
        payload = f"{OAUTH_STATE_PREFIX}:{nonce}:{expires}"
        signature = auth.digest(payload)
        return f"{nonce}.{expires}.{signature}"

    def consume(self, auth: Auth, state: str) -> None:
        if len(auth.secret) < 32 or len(state) > 512:
            raise DomainError("FEISHU_STATE_INVALID", "飞书登录状态无效")
        try:
            nonce, expires_raw, signature = state.split(".", 2)
            expires = int(expires_raw)
            payload = f"{OAUTH_STATE_PREFIX}:{nonce}:{expires}"
            expected = auth.digest(payload)
        except (ValueError, DomainError) as error:
            raise DomainError("FEISHU_STATE_INVALID", "飞书登录状态无效") from error
        if not hmac.compare_digest(signature, expected):
            raise DomainError("FEISHU_STATE_INVALID", "飞书登录状态无效")
        now_ms = int(time.time() * 1000)
        if expires <= now_ms:
            raise DomainError("FEISHU_STATE_INVALID", "飞书登录状态无效")
        with self._lock:
            self._prune(time.time())
            if state in self._used:
                raise DomainError("FEISHU_STATE_INVALID", "飞书登录状态无效")
            self._used[state] = time.time() + OAUTH_STATE_TTL_MS / 1000


STATE_STORE = OAuthStateStore()


def role_for_open_id(settings: Settings, open_id: str) -> str | None:
    if open_id in _split_ids(settings.feishu_admin_open_ids):
        return "admin"
    if open_id in _split_ids(settings.feishu_recruiter_open_ids):
        return "recruiter"
    return None


def decrypt_event(encrypt_key: str, encrypted: str) -> Object:
    try:
        raw = base64.b64decode(encrypted)
        if len(raw) < 17 or len(raw) % 16 != 0:
            raise ValueError("ciphertext length")
        key = hashlib.sha256(encrypt_key.encode()).digest()
        iv, body = raw[:16], raw[16:]
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(body) + decryptor.finalize()
        pad = padded[-1]
        if pad < 1 or pad > 16 or padded[-pad:] != bytes([pad]) * pad:
            raise ValueError("pkcs7")
        payload = json.loads(padded[:-pad].decode())
    except (ValueError, json.JSONDecodeError, UnicodeError) as error:
        raise DomainError("FEISHU_SIGNATURE_INVALID", "飞书事件签名或解密失败") from error
    if not isinstance(payload, dict):
        raise DomainError("FEISHU_SIGNATURE_INVALID", "飞书事件签名或解密失败")
    return payload


def encrypt_event_for_tests(encrypt_key: str, payload: Object, iv: bytes | None = None) -> str:
    """Deterministic helper for offline tests only."""
    key = hashlib.sha256(encrypt_key.encode()).digest()
    vector = iv if iv is not None else b"\0" * 16
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    pad = 16 - (len(body) % 16)
    body = body + bytes([pad]) * pad
    encryptor = Cipher(algorithms.AES(key), modes.CBC(vector)).encryptor()
    return base64.b64encode(vector + encryptor.update(body) + encryptor.finalize()).decode()


def event_token(payload: Object) -> str:
    if payload.get("token") is not None:
        return str(payload.get("token") or "")
    header = payload.get("header")
    if isinstance(header, dict) and header.get("token") is not None:
        return str(header.get("token") or "")
    return ""


def parse_event_body(settings: Settings, body: Object) -> Object:
    require_feishu_configured(settings)
    if not settings.feishu_verification_token.strip():
        raise DomainError("FEISHU_NOT_CONFIGURED", "飞书应用未配置")
    payload = body
    if settings.feishu_encrypt_key and "encrypt" in body:
        payload = decrypt_event(settings.feishu_encrypt_key, str(body.get("encrypt") or ""))
    token = event_token(payload)
    expected = settings.feishu_verification_token
    if not token or not hmac.compare_digest(token, expected):
        raise DomainError("FEISHU_SIGNATURE_INVALID", "飞书事件签名或解密失败")
    return payload
