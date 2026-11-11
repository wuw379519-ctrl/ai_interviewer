"""Admin operations, retention, records, audit, and erasure routes."""
from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from interviewer import assessment, governance, records
from interviewer.contracts import ReportDocument
from interviewer.errors import DomainError
from interviewer.modules.common import actor_of, recruiter_write, service_of
from interviewer.operations import Operations

from .schemas import CleanupInput, DeleteInput, EmptyInput, Object, RetentionInput


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/admin/operations", tags=["governance"])
    def metrics(request: Request) -> Object:
        operations = cast(Operations, request.app.state.operations)
        return operations.snapshot()

    @router.get("/api/admin/retention", tags=["governance"])
    def retention(request: Request) -> Object:
        service = service_of(request)
        with service.database.unit_of_work() as connection:
            service.audit(connection, "retention.previewed", "workspace", actor=actor_of(request))
            return {"policy": service.policy(connection), "preview": governance.cleanup_preview(service, connection)}

    @router.patch("/api/admin/retention", tags=["governance"])
    def policy(request: Request, body: RetentionInput) -> Response:
        return recruiter_write(request, "PATCH /admin/retention", body,
                               lambda svc, connection, actor: governance.update_policy(svc, connection, body, actor), fresh=False)

    @router.post("/api/admin/retention/run", tags=["governance"])
    def cleanup(request: Request, body: CleanupInput) -> Response:
        return recruiter_write(request, "POST /admin/retention/run", body,
                               lambda svc, connection, actor: governance.run_cleanup(svc, connection, body, actor))

    @router.get("/api/admin/candidates", tags=["governance"])
    def candidates(request: Request, before: UUID | None = None) -> Object:
        service = service_of(request)
        with service.database.unit_of_work() as connection:
            return governance.candidates_page(service, connection, str(before) if before else None)

    @router.get("/api/admin/interviews", tags=["interviews"])
    def list_interview_records(request: Request, before: UUID | None = None) -> Object:
        service = service_of(request)
        with service.database.unit_of_work() as connection:
            return records.page(service, connection, str(before) if before else None)

    @router.get("/api/admin/interviews/{interview_id}", tags=["interviews"])
    def interview_record(request: Request, interview_id: UUID) -> Object:
        service = service_of(request)
        with service.database.unit_of_work() as connection:
            return records.detail(service, connection, str(interview_id), actor_of(request))

    @router.post("/api/admin/interviews/{interview_id}/score", tags=["assessment"], response_model=ReportDocument)
    def admin_score(request: Request, interview_id: UUID, body: EmptyInput) -> Response:
        return recruiter_write(request, f"POST /admin/interviews/{interview_id}/score", body,
                               lambda svc, connection, actor: assessment.generate_report(svc, connection, str(interview_id), False, actor),
                               interview_id=str(interview_id), report=True, fresh=True)

    @router.get("/api/admin/audit", tags=["governance"])
    def audit(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 25, before: UUID | None = None,
              action: Annotated[str | None, Query(pattern=r"^[a-z_.]+$", max_length=80)] = None,
              interview_id: Annotated[UUID | None, Query(alias="interviewId")] = None) -> Object:
        service = service_of(request)
        with service.database.unit_of_work() as connection:
            return governance.audit_page(service, connection, actor_of(request), str(before) if before else None, action,
                                         str(interview_id) if interview_id else None, limit)

    @router.get("/api/candidates/{candidate_id}", tags=["governance"])
    def preview(request: Request, candidate_id: UUID) -> Object:
        service = service_of(request)
        with service.database.unit_of_work() as connection:
            return governance.preview_erasure(service, connection, str(candidate_id))

    @router.delete("/api/candidates/{candidate_id}", tags=["governance"])
    def erase(request: Request, candidate_id: UUID, body: DeleteInput) -> Response:
        if str(candidate_id) != body.confirm_candidate_id:
            raise DomainError("VALIDATION_FAILED", "确认编号与待删除候选人不一致")
        return recruiter_write(request, f"DELETE /candidates/{candidate_id}", body,
                               lambda svc, connection, actor: governance.erase_candidate(svc, connection, str(candidate_id), body.reason, actor), str(candidate_id))

    return router
