"""Password login and admin logout (tags: identity)."""
from __future__ import annotations

import hmac
import time

from fastapi import APIRouter, Request
from fastapi.responses import Response

from interviewer.auth import Actor
from interviewer.errors import DomainError
from interviewer.modules.common import actor_of, send, service_of
from interviewer.service import Result

from .schemas import EmptyInput, LoginInput


def build_router() -> APIRouter:
    router = APIRouter()

    def login(request: Request, body: LoginInput, admin_only: bool = False) -> Response:
        service = service_of(request)
        settings = service.settings
        database = service.database
        demo_login = settings.demo and not body.username and not body.password
        username = body.username.strip()
        if demo_login:
            role = "admin" if admin_only else "recruiter"
        else:
            role = "admin" if username == settings.admin_username else "recruiter"
            expected_name = settings.admin_username if role == "admin" else settings.recruiter_username
            expected_password = settings.admin_password if role == "admin" else settings.recruiter_password
            if (not username or username != expected_name or not expected_password or
                    not hmac.compare_digest(body.password.encode(), expected_password.encode()) or (admin_only and role != "admin")):
                raise DomainError("UNAUTHORIZED", "账号或密码不正确")
        response = send(Result({"ok": True, "demo": demo_login, "role": role}))
        if not demo_login:
            other = "recruiter" if role == "admin" else "admin"
            response.delete_cookie(f"aii_{other}", path="/", secure=settings.environment == "production", httponly=True, samesite="strict")
        response.set_cookie(f"aii_{role}", service.auth.session(int(time.time() * 1000) + 8 * 3600000, role),
                            max_age=8 * 3600, httponly=True, secure=settings.environment == "production", samesite="strict", path="/")
        with database.unit_of_work() as connection:
            service.audit(connection, f"{role}.login", "workspace", actor=Actor(role, role, "工作空间身份"))
        return response

    @router.post("/api/auth/login", tags=["identity"])
    def recruiter_login(request: Request, body: LoginInput) -> Response:
        return login(request, body)

    @router.post("/api/admin/login", tags=["identity"])
    def admin_login(request: Request, body: LoginInput) -> Response:
        return login(request, body, admin_only=True)

    return router


def build_logout_router() -> APIRouter:
    """Registered after Feishu routes so OpenAPI path order matches the pre-split app."""
    router = APIRouter()

    @router.post("/api/admin/logout", tags=["identity"])
    def admin_logout(request: Request, _body: EmptyInput) -> Response:
        service = service_of(request)
        settings = service.settings
        with service.database.unit_of_work() as connection:
            service.audit(connection, "admin.logout", "workspace", actor=actor_of(request))
        response = send(Result({"ok": True}))
        response.delete_cookie("aii_admin", path="/", secure=settings.environment == "production", httponly=True, samesite="strict")
        return response

    return router
