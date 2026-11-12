"""Local practice chat using the same safety-checked dialogue provider as the CLI."""
from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Sequence
from datetime import timedelta
from typing import cast

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from python_multipart import FormParser
from python_multipart.multipart import Field as FormField, File as FormFile, parse_options_header
from sqlalchemy import select

from . import database as db
from .errors import DomainError
from .llm_service import MAX_CHAT_MESSAGE_CHARS, OPENING_MESSAGE, ChatConfig, LLMService
from .repository import StorageSession
from .safety import redact
from .service import Service
from .speech import read_limited
from .stt_service import MAX_FILE_BYTES, uploaded_wave

CHAT_PATH = "/api/interview/chat"
SESSION_PATH = "/api/interview/session"
WEB_ORIGIN = "http://localhost:5173"
MAX_BODY_BYTES = MAX_FILE_BYTES + 65536
RETENTION_DAYS = 90


class ChatConsent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    accepted: bool
    consent_version: str = Field(min_length=1, max_length=100)


class ChatInfo(BaseModel):
    consent_version: str
    consent_text: str
    audio_enabled: bool
    fake: bool
    opening: str = OPENING_MESSAGE


class ChatReply(BaseModel):
    user_text: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_CHARS)
    ai_reply: str = Field(min_length=1, max_length=400)


class StoredTurn(ChatReply):
    key: str
    fingerprint: str


class ChatHistory(BaseModel):
    turns: Sequence[ChatReply]


_turns = TypeAdapter(list[StoredTurn])


def parse_chat_form(body: bytes, content_type: str) -> tuple[str, bytes | None]:
    kind, options = parse_options_header(content_type.encode())
    boundary = options.get(b"boundary", b"")
    if kind != b"multipart/form-data" or not 0 < len(boundary) <= 200:
        raise DomainError("VALIDATION_FAILED", "请使用 multipart/form-data 提交文字或音频文件")
    text: str | None = None
    audio: bytes | None = None
    complete = False

    def on_text(value: FormField) -> None:
        nonlocal text
        if value.field_name != b"text" or text is not None:
            raise DomainError("VALIDATION_FAILED", "只接受一个 text 字段")
        text = (value.value or b"").decode("utf-8").strip()
        if len(text) > MAX_CHAT_MESSAGE_CHARS or "\x00" in text:
            raise DomainError("VALIDATION_FAILED", "回答须为最多4000字的有效文字")

    def on_file(value: FormFile) -> None:
        nonlocal audio
        try:
            if value.field_name != b"file" or not value.file_name or audio is not None or not value.in_memory:
                raise DomainError("VALIDATION_FAILED", "只接受一个 file 音频文件")
            if not 0 < value.size <= MAX_FILE_BYTES:
                raise DomainError("VALIDATION_FAILED", "音频文件须非空且不超过16MiB")
            value.file_object.seek(0)
            audio = value.file_object.read()
        finally:
            value.close()

    def on_end() -> None:
        nonlocal complete
        complete = True

    try:
        parser = FormParser("multipart/form-data", on_text, on_file, on_end, boundary=boundary,
                            config={"MAX_BODY_SIZE": MAX_BODY_BYTES, "MAX_MEMORY_FILE_SIZE": MAX_BODY_BYTES,
                                    "MAX_FIELDS": 1, "MAX_FIELD_SIZE": 4 * MAX_CHAT_MESSAGE_CHARS,
                                    "UPLOAD_ERROR_ON_BAD_CTE": True})
        parser.write(body)
        parser.finalize()
    except (ValueError, OSError) as error:
        raise DomainError("VALIDATION_FAILED", "文字或音频表单无法读取") from error
    if not complete or bool(text) == (audio is not None):
        raise DomainError("VALIDATION_FAILED", "请仅填写文字或上传一个音频文件")
    return text or "", audio


def _token_hash(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not re.fullmatch(r"[a-f0-9]{64}", token):
        raise DomainError("UNAUTHORIZED", "请先建立练习会话并确认知情说明")
    return hashlib.sha256(token.encode()).hexdigest()


class PracticeChat:
    def __init__(self, service: Service) -> None:
        self.service = service
        self.lock = threading.Lock()
        self.active: set[str] = set()
        self.llm: LLMService | None = None

    def info(self) -> ChatInfo:
        settings = self.service.settings
        fake, audio = settings.provider == "fake", settings.stt_provider == "whisper"
        version = f"web-chat-v1-{settings.provider}-{'audio' if audio else 'text'}"
        processing = "由本机演示模型生成追问。" if fake else "文字脱敏后会发送给服务端配置的模型端点以生成追问。"
        speech = "上传音频会由本地 Whisper 转写，文件不保存。" if audio else "当前仅接收文字。"
        return ChatInfo(consent_version=version, audio_enabled=audio, fake=fake,
                        consent_text=f"此会话用于 AI 面试练习。{speech}{processing}"
                                     "对话最多可访问90天，你可以随时删除。请勿提交真实招聘资料或联系方式。")

    def _row(self, connection: StorageSession, digest: str) -> db.Row | None:
        from .tenancy import current_tenant
        rows = db.rows(connection, select(db.practice_sessions).where(
            db.practice_sessions.c.token_hash == digest,
            db.practice_sessions.c.tenant_id == current_tenant(),
        ))
        return rows[0] if rows else None

    def _session(self, connection: StorageSession, digest: str) -> db.Row:
        row = self._row(connection, digest)
        if row is None or db.utc(row["retained_until"]) <= db.now():
            raise DomainError("UNAUTHORIZED", "练习会话不存在或已到期，请重新开始")
        if row["consent_version"] != self.info().consent_version:
            raise DomainError("CONSENT_REQUIRED", "处理方式已改变，请删除旧会话并重新确认说明")
        return row

    def admit(self, request: Request) -> None:
        if self.service.settings.environment != "development":
            raise DomainError("FORBIDDEN", "面试练习接口仅在开发模式开放")
        if request.headers.get("origin", WEB_ORIGIN) != WEB_ORIGIN:
            raise DomainError("FORBIDDEN", "仅允许指定的本地练习页面访问")
        if request.url.path == SESSION_PATH and request.method == "PUT":
            ip = request.client.host if request.client else "local"
            self.service.auth.limit(f"practice:consent:{ip}", 20)
            _token_hash(request)
        if request.url.path == CHAT_PATH and request.method == "POST":
            digest = _token_hash(request)
            with self.service.database.unit_of_work() as connection:
                request.state.practice_id = str(self._session(connection, digest)["id"])
            self.service.auth.limit(f"practice:answer:{digest}", 20)

    def start(self, request: Request, body: ChatConsent) -> ChatHistory:
        digest, version = _token_hash(request), self.info().consent_version
        if not body.accepted or body.consent_version != version:
            raise DomainError("CONSENT_REQUIRED", "请明确同意当前版本的知情说明")
        with self.service.database.unit_of_work() as connection:
            table = db.practice_sessions
            db.command(connection, table.delete().where(table.c.retained_until <= db.now()))
            row = self._row(connection, digest)
            if row is None:
                row = db.insert(connection, table, {"token_hash": digest, "consent_version": version, "turns": [],
                                                   "retained_until": db.now() + timedelta(days=RETENTION_DAYS)})
                self.service.audit(connection, "practice.consented", str(row["id"]), {"consentVersion": version})
            else:
                row = self._session(connection, digest)
            return ChatHistory(turns=_turns.validate_python(row["turns"]))

    def history(self, request: Request) -> ChatHistory:
        with self.service.database.unit_of_work() as connection:
            row = self._session(connection, _token_hash(request))
            return ChatHistory(turns=_turns.validate_python(row["turns"]))

    def erase(self, request: Request) -> Response:
        digest = _token_hash(request)
        with self.service.database.unit_of_work() as connection:
            row = self._row(connection, digest)
            if row:
                table = db.practice_sessions
                db.command(connection, table.delete().where(table.c.id == row["id"]))
                self.service.audit(connection, "practice.erased", str(row["id"]))
        return Response(status_code=204)

    def _model(self) -> LLMService:
        with self.lock:
            if self.llm is None:
                try:
                    self.llm = LLMService(ChatConfig.from_env(provider=self.service.settings.provider))
                except (ValidationError, ValueError) as error:
                    raise DomainError("NOT_READY", "请检查服务端对话模型配置") from error
            return self.llm

    def _turns(self, connection: StorageSession, digest: str, identity: str) -> list[StoredTurn]:
        row = self._session(connection, digest)
        if row["id"] != identity:
            raise DomainError("RESOURCE_CONFLICT", "练习会话已变化，请刷新")
        return _turns.validate_python(row["turns"])

    def _answer(self, digest: str, identity: str, key: str, text: str, audio: bytes | None) -> ChatReply:
        fingerprint = hashlib.sha256(b"file:" + audio if audio is not None else b"text:" + text.encode()).hexdigest()
        with self.service.database.unit_of_work() as connection:
            previous = self._turns(connection, digest, identity)
        for turn in previous:
            if key and turn.key == key:
                if turn.fingerprint != fingerprint:
                    raise DomainError("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_BODY", "幂等键对应不同请求内容")
                return turn
        if audio is not None:
            settings = self.service.settings
            if settings.stt_provider != "whisper":
                raise DomainError("SPEECH_UNAVAILABLE", "请启用本机 Whisper，或改用文字回答")
            text = self.service.whisper.transcribe(uploaded_wave(settings, audio)).text
        text = redact(text.strip())
        if not 0 < len(text) <= MAX_CHAT_MESSAGE_CHARS or "\x00" in text:
            raise DomainError("VALIDATION_FAILED", "回答须为1至4000字的有效文字")
        with self.service.database.unit_of_work() as connection:
            if self._turns(connection, digest, identity) != previous:
                raise DomainError("RESOURCE_CONFLICT", "对话已变化，请刷新后重试")
        messages = [{"role": "assistant", "content": OPENING_MESSAGE}]
        for turn in previous:
            messages.extend(({"role": "user", "content": turn.user_text}, {"role": "assistant", "content": turn.ai_reply}))
        messages.append({"role": "user", "content": text})
        result = StoredTurn(user_text=text, ai_reply=self._model().chat(messages), key=key, fingerprint=fingerprint)
        with self.service.database.unit_of_work() as connection:
            if self._turns(connection, digest, identity) != previous:
                raise DomainError("RESOURCE_CONFLICT", "对话已变化，请刷新后重试")
            db.update(connection, db.practice_sessions, identity, turns=[turn.model_dump() for turn in [*previous, result]])
        return result

    def _submit(self, digest: str, identity: str, key: str, body: bytes, content_type: str) -> ChatReply:
        with self.lock:
            if identity in self.active:
                raise DomainError("RESOURCE_CONFLICT", "当前回答正在处理，请稍后重试")
            self.active.add(identity)
        try:
            return self._answer(digest, identity, key, *parse_chat_form(body, content_type))
        finally:
            with self.lock:
                self.active.remove(identity)

    async def answer(self, request: Request) -> ChatReply:
        key = request.headers.get("idempotency-key", "").strip()
        if len(key) > 200:
            raise DomainError("VALIDATION_FAILED", "幂等键不能超过200字符")
        body = await read_limited(request, MAX_BODY_BYTES)
        return await run_in_threadpool(self._submit, _token_hash(request), cast(str, request.state.practice_id),
                                       key, body, request.headers.get("content-type", ""))

    def mount(self, app: FastAPI) -> None:
        routes = app.add_api_route
        routes(CHAT_PATH, self.info, methods=["GET"], response_model=ChatInfo, tags=["practice"])
        routes(CHAT_PATH, self.answer, methods=["POST"], response_model=ChatReply, tags=["practice"], openapi_extra={
            "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
                "type": "object", "properties": {"file": {"type": "string", "format": "binary"},
                                                  "text": {"type": "string", "maxLength": MAX_CHAT_MESSAGE_CHARS}},
                "oneOf": [{"required": ["file"]}, {"required": ["text"]}],
            }}}},
        })
        routes(SESSION_PATH, self.start, methods=["PUT"], response_model=ChatHistory, tags=["practice"])
        routes(SESSION_PATH, self.history, methods=["GET"], response_model=ChatHistory, tags=["practice"])
        routes(SESSION_PATH, self.erase, methods=["DELETE"], status_code=204, tags=["practice"])
