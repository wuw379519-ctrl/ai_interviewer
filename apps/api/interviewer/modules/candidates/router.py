"""Candidate create and resume upload (tags: candidates)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import ValidationError

from interviewer import speech
from interviewer.errors import DomainError
from interviewer.modules.common import recruiter_write

from .schemas import CandidateCreate, ResumeText


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/candidates", tags=["candidates"], status_code=201)
    def create_candidate(request: Request, body: CandidateCreate) -> Response:
        return recruiter_write(request, "POST /candidates", body, lambda svc, connection, actor: svc.create_candidate(connection, body, actor))

    @router.post("/api/candidates/{candidate_id}/resume", tags=["candidates"], status_code=201)
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

    return router
