"""WebSocket entry: /ws/interview/{session_id} — auth + heartbeat + resume + pipeline."""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import cast
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from interviewer import database as db
from interviewer.realtime.pipeline import RealtimePipeline
from interviewer.proctoring import append_proctor_log
from interviewer.realtime.protocol import (
    AuthMessage,
    CloseMessage,
    EndTurnMessage,
    ErrorMessage,
    EventReplayMessage,
    InterruptMessage,
    PingMessage,
    PongMessage,
    ProctorSignalMessage,
    ReadyMessage,
    StartMessage,
    StateChangedMessage,
    TextInputMessage,
    AudioChunkMessage,
    dump_server_message,
    parse_client_json,
)
from interviewer.realtime.session_store import SessionStore
from interviewer.service import Service
from interviewer.tenancy import DEFAULT_TENANT_ID, reset_current_tenant, set_current_tenant

logger = logging.getLogger("interviewer.realtime")


def build_realtime_router(store: SessionStore) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/interview/{session_id}")
    async def interview_socket(websocket: WebSocket, session_id: str) -> None:
        service = cast(Service, websocket.app.state.service)
        try:
            interview_id = str(UUID(session_id))
        except ValueError:
            await websocket.close(code=4400, reason="invalid session")
            return

        await websocket.accept()
        live = None
        tenant_id = DEFAULT_TENANT_ID
        pipeline: RealtimePipeline | None = None
        try:
            raw = await websocket.receive_text()
            try:
                first = parse_client_json(raw)
            except ValidationError:
                await _send(websocket, ErrorMessage(code="VALIDATION_FAILED", message="首条消息必须是合法 auth"))
                await websocket.close(code=4400)
                return
            if not isinstance(first, AuthMessage):
                await _send(websocket, ErrorMessage(code="UNAUTHORIZED", message="请先发送 auth"))
                await websocket.close(code=4401)
                return

            row, tenant_id = await _authenticate(service, interview_id, first.token)
            if row is None:
                await _send(websocket, ErrorMessage(code="UNAUTHORIZED", message="邀请无效或不属于当前租户"))
                await websocket.close(code=4401)
                return

            live = await store.attach(interview_id, tenant_id, websocket)
            resume_from = int(first.resume_from_seq)
            latest = store.latest_seq(service, interview_id, tenant_id)
            replay = store.events_after(service, interview_id, tenant_id, resume_from)
            await _send(
                websocket,
                ReadyMessage(
                    interviewId=interview_id,
                    status=str(row["status"]),
                    resumeFromSeq=latest,
                    tenantBound=True,
                ),
            )
            if replay:
                await _send(
                    websocket,
                    EventReplayMessage(fromSeq=resume_from, events=list(replay)),
                )

            async def send_locked(message: object) -> None:
                assert live is not None
                async with live.write_lock:
                    await _send(websocket, message)

            pipeline = RealtimePipeline(service=service, session=live, send=send_locked)
            live.pipeline = pipeline

            while True:
                text = await websocket.receive_text()
                try:
                    message = parse_client_json(text)
                except ValidationError:
                    await send_locked(ErrorMessage(code="VALIDATION_FAILED", message="消息格式无效"))
                    continue
                if isinstance(message, PingMessage):
                    await send_locked(PongMessage(t=message.t))
                    continue
                if isinstance(message, CloseMessage):
                    break
                if isinstance(message, StartMessage):
                    await send_locked(
                        StateChangedMessage(status=str(row["status"]), detail={"via": "ws_start_ack"}),
                    )
                    continue
                if isinstance(message, TextInputMessage):
                    await pipeline.handle_text_input(message)
                    continue
                if isinstance(message, AudioChunkMessage):
                    await pipeline.handle_audio_chunk(message)
                    continue
                if isinstance(message, EndTurnMessage):
                    await pipeline.handle_end_turn(message)
                    continue
                if isinstance(message, InterruptMessage):
                    await pipeline.handle_client_interrupt()
                    continue
                if isinstance(message, ProctorSignalMessage):
                    token_ctx = set_current_tenant(tenant_id)
                    try:
                        with service.database.unit_of_work() as connection:
                            append_proctor_log(
                                connection,
                                interview_id,
                                message.signal_type,
                                dict(message.payload),
                            )
                    finally:
                        reset_current_tenant(token_ctx)
                    await send_locked(
                        StateChangedMessage(
                            status=str(row["status"]),
                            detail={"via": "proctor_signal_ack", "signalType": message.signal_type},
                        )
                    )
                    continue
                if isinstance(message, AuthMessage):
                    await send_locked(ErrorMessage(code="VALIDATION_FAILED", message="已认证，勿重复 auth"))
                    continue
        except WebSocketDisconnect:
            logger.info("ws_disconnect interview=%s", interview_id)
        except Exception:
            logger.exception("ws_failed interview=%s", interview_id)
            try:
                await _send(websocket, ErrorMessage(code="INTERNAL_ERROR", message="实时通道异常"))
            except Exception:
                pass
        finally:
            if pipeline is not None:
                pipeline.cancel()
            if live is not None:
                await store.detach(interview_id, live.connection_id)

    return router


async def _send(websocket: WebSocket, message: object) -> None:
    from interviewer.realtime.protocol import ServerMessage

    await websocket.send_text(dump_server_message(cast(ServerMessage, message)))


async def _authenticate(service: Service, interview_id: str, token: str) -> tuple[db.Row | None, str]:
    """Validate invite token; bind tenant from the interview row (never from client)."""
    if not token or len(token) > 256:
        return None, DEFAULT_TENANT_ID
    digest = hashlib.sha256(token.encode()).hexdigest()
    with service.database.unit_of_work() as connection:
        # Lookup by id without tenant filter first (token proves access), then bind tenant.
        row = db.one(connection, db.interviews, interview_id)
        if row is None or not row.get("invite_token_hash"):
            return None, DEFAULT_TENANT_ID
        if not hmac.compare_digest(str(row["invite_token_hash"]), digest):
            return None, DEFAULT_TENANT_ID
        tenant_id = str(row.get("tenant_id") or DEFAULT_TENANT_ID)
        token_ctx = set_current_tenant(tenant_id)
        try:
            # Enforce tenant-scoped required() so cross-tenant forged ids still fail closed.
            from interviewer.tenancy import reset_current_tenant

            try:
                bound = service.interview(connection, interview_id)
            except Exception:
                return None, tenant_id
            if not bound.get("invite_expires_at") or db.utc(bound["invite_expires_at"]) <= db.now():
                return None, tenant_id
            return bound, tenant_id
        finally:
            reset_current_tenant(token_ctx)
