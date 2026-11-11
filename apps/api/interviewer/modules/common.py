"""Shared HTTP helpers for modular routers (behavior preserved from main)."""
from __future__ import annotations

from collections.abc import Callable
from typing import cast

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from interviewer import assessment
from interviewer.auth import Actor
from interviewer.contracts import Contract, Object, ReportDocument, json_object
from interviewer.errors import DomainError
from interviewer.repository import StorageSession
from interviewer.service import Result, Service

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
