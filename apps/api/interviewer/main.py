from __future__ import annotations

import asyncio
import hmac
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, cast
from uuid import UUID, uuid4

from fastapi import FastAPI, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from pydantic import ValidationError
from .repository import StorageSession
from starlette.exceptions import HTTPException

from . import assessment, database as db, feishu, formal, governance, records, speech, tts
from .auth import Actor
from .chat_api import CHAT_PATH, SESSION_PATH, WEB_ORIGIN, PracticeChat
from .contracts import (CandidateCreate, CleanupInput, CompetencySet, ConsentInput, Contract,
                        DeleteInput, EmptyInput, ErrorEnvelope, FeishuOAuthInput, FormalInterviewCreate, GraduateInput, InterviewCreate, JobCreate,
                        LoginInput, MediaInput, Object, PauseInput, PrintInput, ReportDocument,
                        ResumeText, RetentionInput, ReviewInput, RevisionInput, ScoreInput,
                        TurnInput, json_object)
from .errors import DomainError
from .feishu import (FakeFeishu, FeishuPort, LiveFeishu, OAUTH_NONCE_COOKIE, STATE_STORE, oauth_authorize_url,
                     open_id_fingerprint, public_status, role_for_open_id, state_nonce)
from .operations import Operations
from .service import Result, Service
from .settings import Settings

Worker = Callable[[Service, StorageSession, Actor], Result]
CANDIDATE_ACTIONS = {"state", "consent", "start", "turns", "finish", "pause", "withdraw", "media", "transcribe", "tts"}


def send(result: Result, report: bool = False) -> JSONResponse:
    payload = ReportDocument.model_validate(result.payload).payload() if report else json_object(result.payload)
    return JSONResponse(payload, status_code=result.status, headers={"Cache-Control": "no-store"})


def service_of(request: Request) -> Service:
    return cast(Service, request.app.state.service)


def actor_of(request: Request) -> Actor:
    value = request.state.actor
    if not isinstance(value, Actor):
        raise DomainError("UNAUTHORIZED", "请先完成身份验证")
    return value


def recruiter_write(request: Request, scope: str, body: Contract, work: Worker,
                    candidate_id: str | None = None, interview_id: str | None = None,
                    report: bool = False, fresh: bool = False) -> Response:
    service, actor = service_of(request), actor_of(request)
    with service.database.unit_of_work() as connection:
        interview = service.interview(connection, interview_id, report) if interview_id else None
        current = (lambda: assessment.report_document(service, connection, interview_id or "")) if report and (fresh or interview and interview["recruitment_track"] == "graduate_campus") else None
        if scope == "PATCH /admin/retention":
            def current_policy() -> Object:
                return service.policy(connection)
            current = current_policy
        result = service.write(connection, request, scope, body, lambda: work(service, connection, actor),
                               candidate_id, interview_id, current)
        if scope in {"POST /interviews", "POST /formal-interviews"}:
            payload = dict(result.payload)
            payload["inviteToken"] = service.auth.open(str(payload.pop("sealedToken")))
            result = Result(payload, result.status, result.replayed)
        return send(result, report)


def candidate_write(request: Request, identity: str, operation: str, body: Contract,
                    work: Callable[[Service, StorageSession], Result]) -> Result:
    service = service_of(request)
    with service.database.unit_of_work() as connection:
        service.candidate_access(connection, request, identity, operation in {"turns", "transcribe"}, False)
        return service.write(connection, request, f"POST /interviews/{identity}/{operation}", body,
                             lambda: work(service, connection), interview_id=identity)


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
    practice.mount(app)

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
        if path in {"/api/auth/login", "/api/admin/login", "/api/feishu/oauth/callback", "/api/feishu/oauth/start"}:
            service.auth.origin(request)
            service.auth.limit("login:" + (request.client.host if request.client else "local"), 100 if settings.demo else 10)
            return
        matched = re.fullmatch(r"/api/interviews/([^/]+)/([^/]+)", path)
        if matched and matched[2] in CANDIDATE_ACTIONS:
            try:
                identity = str(UUID(matched[1]))
            except ValueError as error:
                raise DomainError("UNAUTHORIZED", "邀请链接无效") from error
            with database.unit_of_work() as connection:
                service.candidate_access(connection, request, identity, matched[2] in {"turns", "transcribe"})
                if matched[2] not in {"state", "consent", "withdraw"}:
                    service.interview(connection, identity, True)
            request.state.actor = Actor("candidate", identity, "候选人")
            return
        admin = path.startswith("/api/admin/") or re.fullmatch(r"/api/candidates/[^/]+", path) and request.method in {"GET", "DELETE"}
        request.state.actor = service.auth.role(request, "admin" if admin else "recruiter")

    @app.middleware("http")
    async def admission_and_metrics(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        identity, started = str(uuid4()), time.perf_counter()
        try:
            # Authentication and versioned-consent admission precede body parsing/reading.
            await run_in_threadpool(admit, request)
            response = await call_next(request)
        except DomainError as error:
            response = send(Result(error.payload(), error.status))
        except Exception as error:
            logging.getLogger("interviewer").error("request_failed type=%s", type(error).__name__)
            response = send(Result(DomainError("INTERNAL_ERROR", "服务内部错误").payload(), 500))
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

    @app.get("/api/health", tags=["operations"])
    def health() -> Object:
        return {"ok": True, "service": "aii-python", "version": "1.0.0", "instanceId": instance_id, "llmProvider": settings.provider, "demoMode": settings.demo,
                "dbDriver": "postgres" if database.postgres else "sqlite", "timestamp": db.iso(db.now())}

    @app.get("/api/ready", tags=["operations"])
    def ready() -> Response:
        issues = settings.deployment_issues()
        if issues:
            raise DomainError("NOT_READY", "部署配置尚未就绪", {"issues": issues})
        try:
            with database.unit_of_work() as connection:
                service.policy(connection)
        except Exception as error:
            raise DomainError("NOT_READY", "数据库或迁移尚未就绪") from error
        return send(Result({"ok": True, "database": "ready", "mode": settings.environment,
                            "speech": "server_configured" if settings.stt_provider == "whisper" or settings.stt_base_url and settings.stt_model else "device_local"}))

    def login(body: LoginInput, admin_only: bool = False) -> Response:
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

    @app.post("/api/auth/login", tags=["identity"])
    def recruiter_login(body: LoginInput) -> Response:
        return login(body)

    @app.post("/api/admin/login", tags=["identity"])
    def admin_login(body: LoginInput) -> Response:
        return login(body, admin_only=True)

    @app.get("/api/feishu/status", tags=["identity"])
    def feishu_status() -> Response:
        return send(Result(public_status(settings)))

    @app.get("/api/feishu/oauth/start", tags=["identity"])
    def feishu_oauth_start() -> Response:
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

    @app.post("/api/feishu/oauth/callback", tags=["identity"])
    def feishu_oauth_callback(request: Request, body: FeishuOAuthInput) -> Response:
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
        with database.unit_of_work() as connection:
            service.audit(connection, "feishu.login", "workspace",
                          {"role": role, "openIdHash": open_id_fingerprint(open_id)},
                          actor=Actor(role, role, "飞书工作空间身份"))
        return response

    @app.post("/api/feishu/events", tags=["identity"])
    async def feishu_events(request: Request) -> Response:
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

    @app.post("/api/admin/logout", tags=["identity"])
    def admin_logout(request: Request, _body: EmptyInput) -> Response:
        with database.unit_of_work() as connection:
            service.audit(connection, "admin.logout", "workspace", actor=actor_of(request))
        response = send(Result({"ok": True}))
        response.delete_cookie("aii_admin", path="/", secure=settings.environment == "production", httponly=True, samesite="strict")
        return response

    @app.get("/api/jobs", tags=["jobs"])
    def list_jobs() -> Object:
        with database.unit_of_work() as connection:
            return service.dashboard(connection)

    @app.post("/api/jobs", tags=["jobs"], status_code=201)
    def create_job(request: Request, body: JobCreate) -> Response:
        return recruiter_write(request, "POST /jobs", body, lambda svc, connection, actor: svc.create_job(connection, body, actor))

    @app.post("/api/jobs/{job_id}/competencies:extract", tags=["jobs"])
    def extract(request: Request, job_id: UUID, body: EmptyInput) -> Response:
        return recruiter_write(request, f"POST /jobs/{job_id}/competencies:extract", body,
                               lambda svc, connection, actor: svc.extract_competencies(connection, str(job_id), actor))

    @app.patch("/api/jobs/{job_id}/competencies", tags=["jobs"])
    def confirm(request: Request, job_id: UUID, body: CompetencySet) -> Response:
        return recruiter_write(request, f"PATCH /jobs/{job_id}/competencies", body,
                               lambda svc, connection, actor: Result(svc.save_competencies(connection, str(job_id), body, True, actor)))

    @app.post("/api/candidates", tags=["candidates"], status_code=201)
    def create_candidate(request: Request, body: CandidateCreate) -> Response:
        return recruiter_write(request, "POST /candidates", body, lambda svc, connection, actor: svc.create_candidate(connection, body, actor))

    @app.post("/api/candidates/{candidate_id}/resume", tags=["candidates"], status_code=201)
    async def resume(request: Request, candidate_id: UUID) -> Response:
        raw = await speech.read_limited(request, 3 * 1024 * 1024)
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            content, name, mime = speech.memory_upload(raw, content_type, "file")
            text, mime = await run_in_threadpool(speech.parse_resume_file, content, name, mime)
        else:
            try:
                text, name, mime = ResumeText.model_validate_json(raw).text, "pasted-resume.txt", "text/plain"
            except ValidationError as error:
                raise DomainError("VALIDATION_FAILED", "请提供20至30000字简历文本") from error
        body = ResumeText(text=text)
        return await run_in_threadpool(recruiter_write, request, f"POST /candidates/{candidate_id}/resume", body,
                                       lambda svc, connection, actor: svc.parse_resume(connection, str(candidate_id), text, name, mime, actor), str(candidate_id))

    @app.post("/api/interviews", tags=["interviews"], status_code=201)
    def create_interview(request: Request, body: InterviewCreate) -> Response:
        return recruiter_write(request, "POST /interviews", body, lambda svc, connection, actor: svc.create_interview(connection, body, actor), body.candidate_id)

    @app.post("/api/formal-interviews", tags=["interviews"], status_code=201)
    def create_formal_interview(request: Request, body: FormalInterviewCreate) -> Response:
        return recruiter_write(request, "POST /formal-interviews", body,
                               lambda svc, connection, actor: formal.create(svc, connection, body, actor))

    @app.get("/api/interviews/{interview_id}/state", tags=["candidate"])
    def state(request: Request, interview_id: UUID) -> Object:
        with database.unit_of_work() as connection:
            service.candidate_access(connection, request, str(interview_id), count_limit=False)
            return service.state(connection, str(interview_id))

    @app.post("/api/interviews/{interview_id}/consent", tags=["candidate"])
    def consent(request: Request, interview_id: UUID, body: ConsentInput) -> Response:
        return send(candidate_write(request, str(interview_id), "consent", body,
                                    lambda svc, connection: svc.submit_consent(connection, str(interview_id), body.consent_version)))

    @app.post("/api/interviews/{interview_id}/start", tags=["candidate"])
    def start(request: Request, interview_id: UUID, body: EmptyInput) -> Response:
        return send(candidate_write(request, str(interview_id), "start", body, lambda svc, connection: svc.start(connection, str(interview_id))))

    @app.post("/api/interviews/{interview_id}/pause", tags=["candidate"])
    def pause(request: Request, interview_id: UUID, body: PauseInput) -> Response:
        return send(candidate_write(request, str(interview_id), "pause", body, lambda svc, connection: svc.pause(connection, str(interview_id), body.paused)))

    @app.post("/api/interviews/{interview_id}/media", tags=["candidate"])
    def media(request: Request, interview_id: UUID, body: MediaInput) -> Response:
        return send(candidate_write(request, str(interview_id), "media", body, lambda svc, connection: svc.media(connection, str(interview_id), body)))

    @app.post("/api/interviews/{interview_id}/finish", tags=["candidate"])
    def finish(request: Request, interview_id: UUID, body: EmptyInput) -> Response:
        return send(candidate_write(request, str(interview_id), "finish", body, lambda svc, connection: svc.finish(connection, str(interview_id))))

    @app.post("/api/interviews/{interview_id}/withdraw", tags=["candidate"])
    def withdraw(request: Request, interview_id: UUID, body: EmptyInput) -> Response:
        return send(candidate_write(request, str(interview_id), "withdraw", body, lambda svc, connection: svc.finish(connection, str(interview_id), True)))

    @app.post("/api/interviews/{interview_id}/turns", tags=["candidate"], response_class=StreamingResponse)
    def turns(request: Request, interview_id: UUID, body: TurnInput) -> Response:
        result = candidate_write(request, str(interview_id), "turns", body, lambda svc, connection: svc.turn(connection, str(interview_id), body))

        async def events() -> AsyncIterator[str]:
            import json
            meta = {key: value for key, value in result.payload.items() if key != "text"}
            meta["replayed"] = result.replayed
            yield "event: meta\ndata: " + json.dumps(meta, ensure_ascii=False, separators=(",", ":")) + "\n\n"
            for fragment in service.provider.stream(str(result.payload["text"])):
                yield "event: delta\ndata: " + json.dumps({"text": fragment}, ensure_ascii=False, separators=(",", ":")) + "\n\n"
                await asyncio.sleep(0.008)
            yield "event: done\ndata: " + json.dumps(json_object(result.payload), ensure_ascii=False, separators=(",", ":")) + "\n\n"
        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @app.post("/api/interviews/{interview_id}/transcribe", tags=["candidate"])
    async def transcribe(request: Request, interview_id: UUID) -> Response:
        await run_in_threadpool(speech.check_speech, service, request, str(interview_id))
        raw = await speech.read_limited(request, speech.MAX_AUDIO_BYTES + 65536)
        content, _name, _mime = speech.memory_upload(raw, request.headers.get("content-type", ""), "audio")
        return send(await run_in_threadpool(speech.transcribe, service, request, str(interview_id), content))

    @app.get("/api/interviews/{interview_id}/tts", tags=["candidate"], response_class=Response,
             responses={200: {"content": {"audio/mpeg": {"schema": {"type": "string", "format": "binary"}}}}})
    async def question_audio(request: Request, interview_id: UUID, questionSeq: Annotated[int, Query(ge=1)],
                             turnSeq: Annotated[int, Query(ge=1)]) -> Response:
        identity = str(interview_id)
        text = await run_in_threadpool(tts.current_question, service, request, identity, questionSeq, turnSeq)
        service.auth.limit(f"tts:{identity}", 20)
        audio = await service.tts.synthesize(text)
        await run_in_threadpool(tts.current_question, service, request, identity, questionSeq, turnSeq, len(audio))
        return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.post("/api/interviews/{interview_id}/score", tags=["assessment"], response_model=ReportDocument)
    def score(request: Request, interview_id: UUID, body: ScoreInput) -> Response:
        return recruiter_write(request, f"POST /interviews/{interview_id}/score", body,
                               lambda svc, connection, actor: assessment.generate_report(svc, connection, str(interview_id), body.rerun, actor),
                               interview_id=str(interview_id), report=True)

    @app.get("/api/interviews/{interview_id}/report", tags=["assessment"], response_model=ReportDocument)
    def report(request: Request, interview_id: UUID) -> Response:
        with database.unit_of_work() as connection:
            return send(Result(assessment.report_document(service, connection, str(interview_id), True, actor_of(request))), True)

    @app.patch("/api/scores/{score_id}", tags=["assessment"], response_model=ReportDocument)
    def revise(request: Request, score_id: UUID, body: RevisionInput) -> Response:
        with database.unit_of_work() as connection:
            score_row = service.required(connection, db.scores, str(score_id), "INTERVIEW_NOT_FOUND")
            identity = str(score_row["interview_id"])
        return recruiter_write(request, f"PATCH /scores/{score_id}", body,
                               lambda svc, connection, actor: assessment.revise_score(svc, connection, str(score_id), body, actor), interview_id=identity, report=True)

    @app.patch("/api/interviews/{interview_id}/eligibility", tags=["assessment"], response_model=ReportDocument)
    def eligibility(request: Request, interview_id: UUID, body: GraduateInput) -> Response:
        return recruiter_write(request, f"PATCH /interviews/{interview_id}/eligibility", body,
                               lambda svc, connection, actor: assessment.verify_graduate(svc, connection, str(interview_id), body, actor), interview_id=str(interview_id), report=True, fresh=True)

    @app.post("/api/interviews/{interview_id}/review", tags=["assessment"], response_model=ReportDocument)
    def review(request: Request, interview_id: UUID, body: ReviewInput) -> Response:
        return recruiter_write(request, f"POST /interviews/{interview_id}/review", body,
                               lambda svc, connection, actor: assessment.review_report(svc, connection, str(interview_id), body, actor), interview_id=str(interview_id), report=True)

    @app.post("/api/interviews/{interview_id}/print", tags=["assessment"])
    def print_report(request: Request, interview_id: UUID, body: PrintInput) -> Response:
        def work(svc: Service, connection: StorageSession, actor: Actor) -> Result:
            document = assessment.report_document(svc, connection, str(interview_id))
            if document["revision"] != body.expected_revision:
                raise DomainError("RESOURCE_CONFLICT", "报告已更新，请刷新后打印")
            svc.audit(connection, "report.print_requested", str(interview_id), {"revision": body.expected_revision}, actor, str(interview_id))
            return Result({"ok": True})
        return recruiter_write(request, f"POST /interviews/{interview_id}/print", body, work, interview_id=str(interview_id))

    @app.get("/api/admin/operations", tags=["governance"])
    def metrics() -> Object:
        return operations.snapshot()

    @app.get("/api/admin/retention", tags=["governance"])
    def retention(request: Request) -> Object:
        with database.unit_of_work() as connection:
            service.audit(connection, "retention.previewed", "workspace", actor=actor_of(request))
            return {"policy": service.policy(connection), "preview": governance.cleanup_preview(service, connection)}

    @app.patch("/api/admin/retention", tags=["governance"])
    def policy(request: Request, body: RetentionInput) -> Response:
        return recruiter_write(request, "PATCH /admin/retention", body,
                               lambda svc, connection, actor: governance.update_policy(svc, connection, body, actor), fresh=False)

    @app.post("/api/admin/retention/run", tags=["governance"])
    def cleanup(request: Request, body: CleanupInput) -> Response:
        return recruiter_write(request, "POST /admin/retention/run", body,
                               lambda svc, connection, actor: governance.run_cleanup(svc, connection, body, actor))

    @app.get("/api/admin/candidates", tags=["governance"])
    def candidates(before: UUID | None = None) -> Object:
        with database.unit_of_work() as connection:
            return governance.candidates_page(service, connection, str(before) if before else None)

    @app.get("/api/admin/interviews", tags=["interviews"])
    def list_interview_records(before: UUID | None = None) -> Object:
        with database.unit_of_work() as connection:
            return records.page(service, connection, str(before) if before else None)

    @app.get("/api/admin/interviews/{interview_id}", tags=["interviews"])
    def interview_record(request: Request, interview_id: UUID) -> Object:
        with database.unit_of_work() as connection:
            return records.detail(service, connection, str(interview_id), actor_of(request))

    @app.post("/api/admin/interviews/{interview_id}/score", tags=["assessment"], response_model=ReportDocument)
    def admin_score(request: Request, interview_id: UUID, body: EmptyInput) -> Response:
        return recruiter_write(request, f"POST /admin/interviews/{interview_id}/score", body,
                               lambda svc, connection, actor: assessment.generate_report(svc, connection, str(interview_id), False, actor),
                               interview_id=str(interview_id), report=True, fresh=True)

    @app.get("/api/admin/audit", tags=["governance"])
    def audit(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 25, before: UUID | None = None,
              action: Annotated[str | None, Query(pattern=r"^[a-z_.]+$", max_length=80)] = None, interview_id: Annotated[UUID | None, Query(alias="interviewId")] = None) -> Object:
        with database.unit_of_work() as connection:
            return governance.audit_page(service, connection, actor_of(request), str(before) if before else None, action, str(interview_id) if interview_id else None, limit)

    @app.get("/api/candidates/{candidate_id}", tags=["governance"])
    def preview(candidate_id: UUID) -> Object:
        with database.unit_of_work() as connection:
            return governance.preview_erasure(service, connection, str(candidate_id))

    @app.delete("/api/candidates/{candidate_id}", tags=["governance"])
    def erase(request: Request, candidate_id: UUID, body: DeleteInput) -> Response:
        if str(candidate_id) != body.confirm_candidate_id:
            raise DomainError("VALIDATION_FAILED", "确认编号与待删除候选人不一致")
        return recruiter_write(request, f"DELETE /candidates/{candidate_id}", body,
                               lambda svc, connection, actor: governance.erase_candidate(svc, connection, str(candidate_id), body.reason, actor), str(candidate_id))

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
