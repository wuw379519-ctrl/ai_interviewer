"""Feishu status, OAuth, and event callbacks (tags: identity)."""
from __future__ import annotations

import hmac
import logging
import time
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from interviewer import feishu
from interviewer.auth import Actor
from interviewer.contracts import json_object
from interviewer.errors import DomainError
from interviewer.feishu import (FeishuPort, OAUTH_NONCE_COOKIE, STATE_STORE, oauth_authorize_url,
                                open_id_fingerprint, public_status, role_for_open_id, state_nonce)
from interviewer.modules.common import send, service_of
from interviewer.service import Result

from .schemas import FeishuOAuthInput


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/feishu/status", tags=["identity"])
    def feishu_status(request: Request) -> Response:
        return send(Result(public_status(service_of(request).settings)))

    @router.get("/api/feishu/oauth/start", tags=["identity"])
    def feishu_oauth_start(request: Request) -> Response:
        service = service_of(request)
        settings = service.settings
        feishu.require_feishu_configured(settings)
        if not settings.feishu_oauth_redirect_uri.strip():
            raise DomainError("FEISHU_NOT_CONFIGURED", "飞书应用未配置")
        state = STATE_STORE.issue(service.auth)
        response = RedirectResponse(oauth_authorize_url(settings, state), status_code=302)
        response.set_cookie(
            OAUTH_NONCE_COOKIE, state_nonce(state), max_age=480, httponly=True,
            secure=settings.environment == "production", samesite="lax", path="/",
        )
        return response

    @router.post("/api/feishu/oauth/callback", tags=["identity"])
    def feishu_oauth_callback(request: Request, body: FeishuOAuthInput) -> Response:
        service = service_of(request)
        settings = service.settings
        feishu.require_feishu_configured(settings)
        STATE_STORE.consume(service.auth, body.state)
        cookie_nonce = request.cookies.get(OAUTH_NONCE_COOKIE, "")
        if not cookie_nonce or not hmac.compare_digest(cookie_nonce, state_nonce(body.state)):
            raise DomainError("FEISHU_STATE_INVALID", "飞书登录状态无效")
        port = cast(FeishuPort, request.app.state.feishu)
        open_id = port.exchange_code(body.code)
        role = role_for_open_id(settings, open_id)
        if role is None:
            raise DomainError("FEISHU_ROLE_NOT_ALLOWED", "飞书账号不在工作台白名单")
        response = send(Result({"ok": True, "role": role}))
        other = "recruiter" if role == "admin" else "admin"
        response.delete_cookie(f"aii_{other}", path="/", secure=settings.environment == "production", httponly=True, samesite="strict")
        response.delete_cookie(OAUTH_NONCE_COOKIE, path="/", secure=settings.environment == "production", httponly=True, samesite="lax")
        response.set_cookie(f"aii_{role}", service.auth.session(int(time.time() * 1000) + 8 * 3600000, role),
                            max_age=8 * 3600, httponly=True, secure=settings.environment == "production", samesite="strict", path="/")
        with service.database.unit_of_work() as connection:
            service.audit(connection, "feishu.login", "workspace",
                          {"role": role, "openIdHash": open_id_fingerprint(open_id)},
                          actor=Actor(role, role, "飞书工作空间身份"))
        return response

    @router.post("/api/feishu/events", tags=["identity"])
    async def feishu_events(request: Request) -> Response:
        settings = service_of(request).settings
        raw: object = await request.json()
        body = json_object(raw if isinstance(raw, dict) else {})
        payload = feishu.parse_event_body(settings, body)
        if str(payload.get("type") or "") == "url_verification" or "challenge" in payload:
            challenge = payload.get("challenge")
            if challenge is None:
                raise DomainError("VALIDATION_FAILED", "缺少 challenge")
            return JSONResponse({"challenge": challenge}, headers={"Cache-Control": "no-store"})
        header = payload.get("header")
        event_type = str(payload.get("type") or "unknown")
        if isinstance(header, dict) and header.get("event_type"):
            event_type = str(header["event_type"])
        logging.getLogger("interviewer").info("feishu_event_ignored event_type=%s", event_type[:80])
        return send(Result({"ok": True}))

    return router
