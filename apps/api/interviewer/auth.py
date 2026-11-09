from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from fastapi import Request

from .errors import DomainError
from .settings import Settings


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class Actor:
    role: str
    id: str
    name: str


class Auth:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.secret = settings.secret or (secrets.token_hex(32) if settings.demo else "")
        self.limits: dict[str, tuple[int, float]] = {}
        self.lock = threading.RLock()

    def digest(self, value: str) -> str:
        if len(self.secret) < 32:
            raise DomainError("UNAUTHORIZED", "服务未配置身份认证密钥")
        return b64(hmac.digest(self.secret.encode(), value.encode(), "sha256"))

    def session(self, expires: int, role: str) -> str:
        return f"{expires}.{self.digest(f'workspace-account-v1:{role}:{expires}')}"

    def valid_session(self, value: str, role: str) -> bool:
        if len(value) > 256:
            return False
        try:
            expires = int(value.split(".")[0])
            return expires > int(time.time() * 1000) and hmac.compare_digest(value, self.session(expires, role))
        except (ValueError, DomainError):
            return False

    def origin(self, request: Request) -> None:
        origin = request.headers.get("origin")
        if not origin or origin == self.settings.app_base_url.rstrip("/"):
            return
        try:
            actual, configured = urlsplit(origin), urlsplit(self.settings.app_base_url)
            loopback = {"localhost", "127.0.0.1", "::1"}
            if actual.hostname in loopback and configured.hostname in loopback and actual.scheme == configured.scheme and actual.port == configured.port:
                return
        except ValueError:
            pass
        raise DomainError("UNAUTHORIZED", "不允许跨站写入")

    def limit(self, key: str, limit: int = 90, seconds: float = 60) -> None:
        with self.lock:
            current = time.monotonic()
            if len(self.limits) > 5000:
                self.limits = {key: value for key, value in self.limits.items() if value[1] > current}
            count, until = self.limits.get(key, (0, current + seconds))
            if until <= current:
                count, until = 0, current + seconds
            if count >= limit:
                raise DomainError("RATE_LIMITED", "请求过于频繁，请稍后重试")
            self.limits[key] = count + 1, until

    def role(self, request: Request, role: str) -> Actor:
        if request.method != "GET":
            self.origin(request)
        key = self.settings.admin_key if role == "admin" else self.settings.recruiter_key
        if key and hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {key}"):
            return Actor(role, f"{role}-api", "治理 API" if role == "admin" else "工作空间 API")
        if self.valid_session(request.cookies.get(f"aii_{role}", ""), role):
            self.limit(role, 180 if role == "admin" else 90)
            return Actor(role, role, "工作空间管理员" if role == "admin" else "工作空间招聘者")
        if role == "recruiter" and self.valid_session(request.cookies.get("aii_admin", ""), "admin"):
            self.limit("admin", 180)
            return Actor("admin", "admin", "工作空间管理员")
        if role == "admin" and self.valid_session(request.cookies.get("aii_recruiter", ""), "recruiter"):
            raise DomainError("FORBIDDEN", "请使用管理员账号登录")
        raise DomainError("UNAUTHORIZED", "请先登录数据治理管理台" if role == "admin" else "请先登录招聘工作台")

    def seal(self, value: str) -> str:
        iv = secrets.token_bytes(12)
        encrypted = AESGCM(hashlib.sha256(self.secret.encode()).digest()).encrypt(iv, value.encode(), None)
        return b64(iv + encrypted[-16:] + encrypted[:-16])

    def open(self, value: str) -> str:
        try:
            raw = unb64(value)
            return AESGCM(hashlib.sha256(self.secret.encode()).digest()).decrypt(raw[:12], raw[28:] + raw[12:28], None).decode()
        except (ValueError, UnicodeError, InvalidTag) as error:
            raise DomainError("RESOURCE_CONFLICT", "邀请响应的认证密钥已变化") from error
