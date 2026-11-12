from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.exceptions import HTTPException

from . import database as db, feishu
from .auth import Actor
from .chat_api import CHAT_PATH, SESSION_PATH, WEB_ORIGIN, PracticeChat
from .contracts import ErrorEnvelope, Object, ResumeText
from .errors import DomainError
from .feishu import FakeFeishu, LiveFeishu
from .modules.admin.router import build_router as build_admin_router
from .modules.assessment.router import build_router as build_assessment_router
from .modules.auth.router import build_logout_router, build_router as build_auth_router
from .modules.candidates.router import build_router as build_candidates_router
from .modules.common import CANDIDATE_ACTIONS, send
from .modules.feishu.router import build_router as build_feishu_router
from .modules.interviews.router import build_router as build_interviews_router
from .modules.jobs.router import build_router as build_jobs_router
from .modules.operations.router import build_router as build_operations_router
from .modules.practice.router import mount_practice
from .operations import Operations
from .service import Result, Service
from .settings import Settings
from .tenancy import DEFAULT_TENANT_ID, get_current_tenant, reset_current_tenant, set_current_tenant


def create_app(configuration: Settings | None = None) -> FastAPI:
    settings = configuration or Settings.from_env()
    database = db.Database(settings)
    service = Service(settings, database)
    practice = PracticeChat(service)
    operations = Operations(settings.operation_logs)
    instance_id = str(uuid4())

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await run_in_threadpool(database.migrate)
        try:
            if settings.stt_provider == "whisper":
                await run_in_threadpool(service.whisper.load)
            if settings.tts_provider == "edge":
                await run_in_threadpool(service.tts.prepare)
            yield
        finally:
            service.whisper.close()
            database.close()

    app = FastAPI(title="AI Interviewer Python API", version="1.0.0", lifespan=lifespan,
                  openapi_url="/api/openapi.json", docs_url=None, redoc_url=None,
                  responses={code: {"model": ErrorEnvelope} for code in [400, 401, 403, 404, 409, 410, 429, 500, 502, 503]})
    app.state.service = service
    app.state.feishu = LiveFeishu(settings) if feishu.feishu_configured(settings) else FakeFeishu()
    app.state.operations = operations
    app.state.instance_id = instance_id

    # Registration order matches the pre-split app so OpenAPI path order stays stable.
    mount_practice(app, practice)
    app.include_router(build_operations_router())
    app.include_router(build_auth_router())
    app.include_router(build_feishu_router())
    app.include_router(build_logout_router())
    app.include_router(build_jobs_router())
    app.include_router(build_candidates_router())
    app.include_router(build_interviews_router())
    app.include_router(build_assessment_router())
    app.include_router(build_admin_router())

    def admit(request: Request) -> None:
        path = request.url.path
        if path in {CHAT_PATH, SESSION_PATH}:
            practice.admit(request)
            return
        if path in {"/api/health", "/api/ready", "/api/openapi.json", "/api/feishu/status"}:
            return
        if path == "/api/feishu/events":
            service.auth.limit("feishu:events:" + (request.client.host if request.client else "local"), 60)
            return
        host = request.client.host if request.client else "local"
        if path == "/api/feishu/oauth/start":
            service.auth.origin(request)
            service.auth.limit(f"feishu:start:{host}", 60)
            return
        if path in {"/api/auth/login", "/api/admin/login", "/api/feishu/oauth/callback"}:
            service.auth.origin(request)
            service.auth.limit(f"login:{host}", 100 if settings.demo else 10)
            return
        matched = re.fullmatch(r"/api/interviews/([^/]+)/([^/]+)", path)
        if matched and matched[2] in CANDIDATE_ACTIONS:
            try:
                identity = str(UUID(matched[1]))
            except ValueError as error:
                raise DomainError("UNAUTHORIZED", "邀请链接无效") from error
            tenant_id = DEFAULT_TENANT_ID
            with database.unit_of_work() as connection:
                invited = service.candidate_access(
                    connection, request, identity, matched[2] in {"turns", "transcribe"})
                tenant_id = str(invited.get("tenant_id") or DEFAULT_TENANT_ID)
                if matched[2] not in {"state", "consent", "withdraw"}:
                    service.interview(connection, identity, True)
            request.state.actor = Actor("candidate", identity, "候选人", tenant_id)
            return
        admin = path.startswith("/api/admin/") or re.fullmatch(r"/api/candidates/[^/]+", path) and request.method in {"GET", "DELETE"}
        request.state.actor = service.auth.role(request, "admin" if admin else "recruiter")

    @app.middleware("http")
    async def admission_and_metrics(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        identity, started = str(uuid4()), time.perf_counter()
        tenant_token = None
        try:
            # Authentication and versioned-consent admission precede body parsing/reading.
            await run_in_threadpool(admit, request)
            # Bind tenant in this request context (not client-supplied) for all scoped queries.
            tenant_token = set_current_tenant(get_current_tenant(request))
            response = await call_next(request)
        except DomainError as error:
            response = send(Result(error.payload(), error.status))
        except Exception as error:
            logging.getLogger("interviewer").error("request_failed type=%s", type(error).__name__)
            response = send(Result(DomainError("INTERNAL_ERROR", "服务内部错误").payload(), 500))
        finally:
            if tenant_token is not None:
                reset_current_tenant(tenant_token)
        elapsed = max(0, round((time.perf_counter() - started) * 1000))
        path = request.url.path
        operation = "plan" if path in {"/api/interviews", "/api/formal-interviews"} and request.method == "POST" else ""
        suffix = path.rsplit("/", 1)[-1]
        operation = {"state": "state", "turns": "turn", "score": "score", "transcribe": "transcribe"}.get(suffix, operation)
        if suffix in CANDIDATE_ACTIONS and not operation:
            operation = "candidate_write"
        operations.record(operation, response.status_code, elapsed, identity)
        response.headers["X-Request-Id"], response.headers["Server-Timing"] = identity, f"application;dur={elapsed}"
        response.headers["Cache-Control"] = "no-store"
        return response

    if settings.environment == "development":
        app.add_middleware(CORSMiddleware, allow_origins=[WEB_ORIGIN], allow_credentials=False,
                           allow_methods=["GET", "PUT", "POST", "DELETE"],
                           allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])

    @app.exception_handler(DomainError)
    async def domain_error(_request: Request, error: DomainError) -> Response:
        return send(Result(error.payload(), error.status))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError) -> Response:
        details: Object = {"issues": [{"path": ".".join(map(str, row["loc"])), "message": row["msg"]} for row in error.errors()]}
        return send(Result(DomainError("VALIDATION_FAILED", "请求参数校验失败", details).payload(), 400))

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException) -> Response:
        return send(Result({"error": {"code": "NOT_FOUND" if error.status_code == 404 else "VALIDATION_FAILED", "message": "请求的接口不存在" if error.status_code == 404 else "请求未完成", "details": None}}, error.status_code))

    # Middleware performs admission before reading a body; describe that security explicitly.
    schema = app.openapi()
    schema["components"]["securitySchemes"] = {
        "RecruiterSession": {"type": "apiKey", "in": "cookie", "name": "aii_recruiter"},
        "AdminSession": {"type": "apiKey", "in": "cookie", "name": "aii_admin"},
        "CandidateBearer": {"type": "http", "scheme": "bearer"},
        "RecruiterApiKey": {"type": "http", "scheme": "bearer"},
        "AdminApiKey": {"type": "http", "scheme": "bearer"},
    }
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            if method not in {"get", "post", "patch", "delete", "put", "head"}:
                continue
            operation["responses"].pop("422", None)
            suffix = path.rsplit("/", 1)[-1]
            public = path in {"/api/health", "/api/ready", "/api/auth/login", "/api/admin/login",
                              "/api/feishu/status", "/api/feishu/oauth/start", "/api/feishu/oauth/callback",
                              "/api/feishu/events"}
            admin = path.startswith("/api/admin/") or path == "/api/candidates/{candidate_id}" and method in {"get", "delete"}
            candidate = path.startswith("/api/interviews/") and suffix in CANDIDATE_ACTIONS
            operation["security"] = [] if public else [{"CandidateBearer": []}] if candidate else [{"AdminSession": []}, {"AdminApiKey": []}] if admin else [{"RecruiterSession": []}, {"RecruiterApiKey": []}]
            if method in {"post", "patch", "delete", "put"}:
                operation.setdefault("parameters", []).append({"name": "Idempotency-Key", "in": "header", "required": False,
                    "schema": {"type": "string", "maxLength": 200}, "description": "同一身份与请求内容重试复用；不同内容冲突409；删除后缓存410。登录使用可重入会话。"})
    schema["paths"]["/api/candidates/{candidate_id}/resume"]["post"]["requestBody"] = {"required": True, "content": {
        "application/json": {"schema": ResumeText.model_json_schema(by_alias=True)},
        "multipart/form-data": {"schema": {"type": "object", "required": ["file"], "properties": {"file": {"type": "string", "format": "binary"}}}},
    }}
    schema["paths"]["/api/interviews/{interview_id}/transcribe"]["post"]["requestBody"] = {"required": True, "content": {
        "multipart/form-data": {"schema": {"type": "object", "required": ["audio"], "properties": {"audio": {"type": "string", "format": "binary", "description": "16kHz单声道16-bit PCM WAV，最长120秒；内存处理，不保存"}}}}
    }}
    schema["paths"]["/api/interviews/{interview_id}/turns"]["post"]["responses"]["200"]["content"] = {
        "text/event-stream": {"schema": {"type": "string"}, "example": "event: delta\ndata: {\"text\":\"问题\"}\n\nevent: done\ndata: {\"status\":\"interviewing\"}\n\n"}
    }
    app.openapi_schema = schema
    return app


app = create_app()
