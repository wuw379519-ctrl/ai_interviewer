"""Interview creation and candidate session routes."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse

from interviewer import formal, speech, tts
from interviewer.contracts import json_object
from interviewer.modules.common import candidate_write, recruiter_write, send, service_of

from .schemas import (ConsentInput, EmptyInput, FormalInterviewCreate, InterviewCreate, MediaInput,
                      Object, PauseInput, TurnInput)


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/interviews", tags=["interviews"], status_code=201)
    def create_interview(request: Request, body: InterviewCreate) -> Response:
        return recruiter_write(request, "POST /interviews", body, lambda svc, connection, actor: svc.create_interview(connection, body, actor), body.candidate_id)

    @router.post("/api/formal-interviews", tags=["interviews"], status_code=201)
    def create_formal_interview(request: Request, body: FormalInterviewCreate) -> Response:
        return recruiter_write(request, "POST /formal-interviews", body,
                               lambda svc, connection, actor: formal.create(svc, connection, body, actor))

    @router.get("/api/interviews/{interview_id}/state", tags=["candidate"])
    def state(request: Request, interview_id: UUID) -> Object:
        service = service_of(request)
        with service.database.unit_of_work() as connection:
            service.candidate_access(connection, request, str(interview_id), count_limit=False)
            return service.state(connection, str(interview_id))

    @router.post("/api/interviews/{interview_id}/consent", tags=["candidate"])
    def consent(request: Request, interview_id: UUID, body: ConsentInput) -> Response:
        return send(candidate_write(request, str(interview_id), "consent", body,
                                    lambda svc, connection: svc.submit_consent(connection, str(interview_id), body.consent_version)))

    @router.post("/api/interviews/{interview_id}/start", tags=["candidate"])
    def start(request: Request, interview_id: UUID, body: EmptyInput) -> Response:
        return send(candidate_write(request, str(interview_id), "start", body, lambda svc, connection: svc.start(connection, str(interview_id))))

    @router.post("/api/interviews/{interview_id}/pause", tags=["candidate"])
    def pause(request: Request, interview_id: UUID, body: PauseInput) -> Response:
        return send(candidate_write(request, str(interview_id), "pause", body, lambda svc, connection: svc.pause(connection, str(interview_id), body.paused)))

    @router.post("/api/interviews/{interview_id}/media", tags=["candidate"])
    def media(request: Request, interview_id: UUID, body: MediaInput) -> Response:
        return send(candidate_write(request, str(interview_id), "media", body, lambda svc, connection: svc.media(connection, str(interview_id), body)))

    @router.post("/api/interviews/{interview_id}/finish", tags=["candidate"])
    def finish(request: Request, interview_id: UUID, body: EmptyInput) -> Response:
        return send(candidate_write(request, str(interview_id), "finish", body, lambda svc, connection: svc.finish(connection, str(interview_id))))

    @router.post("/api/interviews/{interview_id}/withdraw", tags=["candidate"])
    def withdraw(request: Request, interview_id: UUID, body: EmptyInput) -> Response:
        return send(candidate_write(request, str(interview_id), "withdraw", body, lambda svc, connection: svc.finish(connection, str(interview_id), True)))

    @router.post("/api/interviews/{interview_id}/turns", tags=["candidate"], response_class=StreamingResponse)
    def turns(request: Request, interview_id: UUID, body: TurnInput) -> Response:
        service = service_of(request)
        result = candidate_write(request, str(interview_id), "turns", body, lambda svc, connection: svc.turn(connection, str(interview_id), body))

        async def events() -> AsyncIterator[str]:
            import json
            meta = {key: value for key, value in result.payload.items() if key != "text"}
            meta["replayed"] = result.replayed
            yield "event: meta\ndata: " + json.dumps(meta, ensure_ascii=False, separators=(",", ":")) + "\n\n"
            for fragment in service.gateway.stream(str(result.payload["text"])):
                yield "event: delta\ndata: " + json.dumps({"text": fragment}, ensure_ascii=False, separators=(",", ":")) + "\n\n"
                await asyncio.sleep(0.008)
            yield "event: done\ndata: " + json.dumps(json_object(result.payload), ensure_ascii=False, separators=(",", ":")) + "\n\n"
        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @router.post("/api/interviews/{interview_id}/transcribe", tags=["candidate"])
    async def transcribe(request: Request, interview_id: UUID) -> Response:
        service = service_of(request)
        await run_in_threadpool(speech.check_speech, service, request, str(interview_id))
        raw = await speech.read_limited(request, speech.MAX_AUDIO_BYTES + 65536)
        content, _name, _mime = speech.memory_upload(raw, request.headers.get("content-type", ""), "audio")
        return send(await run_in_threadpool(speech.transcribe, service, request, str(interview_id), content))

    @router.get("/api/interviews/{interview_id}/tts", tags=["candidate"], response_class=Response,
                responses={200: {"content": {"audio/mpeg": {"schema": {"type": "string", "format": "binary"}}}}})
    async def question_audio(request: Request, interview_id: UUID, questionSeq: Annotated[int, Query(ge=1)],
                             turnSeq: Annotated[int, Query(ge=1)]) -> Response:
        service = service_of(request)
        identity = str(interview_id)
        text = await run_in_threadpool(tts.current_question, service, request, identity, questionSeq, turnSeq)
        service.auth.limit(f"tts:{identity}", 20)
        audio = await service.gateway.synthesize(text)
        with service.database.unit_of_work() as connection:
            service.gateway.meter(connection, "tts_chars", float(len(text)), provider=service.gateway.tts.name)
        await run_in_threadpool(tts.current_question, service, request, identity, questionSeq, turnSeq, len(audio))
        return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    return router
