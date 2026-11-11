"""Scoring, report, eligibility, and print routes (tags: assessment)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import Response

from interviewer import assessment, database as db
from interviewer.auth import Actor
from interviewer.errors import DomainError
from interviewer.modules.common import actor_of, recruiter_write, send, service_of
from interviewer.repository import StorageSession
from interviewer.service import Result, Service

from .schemas import GraduateInput, PrintInput, ReportDocument, ReviewInput, RevisionInput, ScoreInput


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/interviews/{interview_id}/score", tags=["assessment"], response_model=ReportDocument)
    def score(request: Request, interview_id: UUID, body: ScoreInput) -> Response:
        return recruiter_write(request, f"POST /interviews/{interview_id}/score", body,
                               lambda svc, connection, actor: assessment.generate_report(svc, connection, str(interview_id), body.rerun, actor),
                               interview_id=str(interview_id), report=True)

    @router.get("/api/interviews/{interview_id}/report", tags=["assessment"], response_model=ReportDocument)
    def report(request: Request, interview_id: UUID) -> Response:
        service = service_of(request)
        with service.database.unit_of_work() as connection:
            return send(Result(assessment.report_document(service, connection, str(interview_id), True, actor_of(request))), True)

    @router.patch("/api/scores/{score_id}", tags=["assessment"], response_model=ReportDocument)
    def revise(request: Request, score_id: UUID, body: RevisionInput) -> Response:
        service = service_of(request)
        with service.database.unit_of_work() as connection:
            score_row = service.required(connection, db.scores, str(score_id), "INTERVIEW_NOT_FOUND")
            identity = str(score_row["interview_id"])
        return recruiter_write(request, f"PATCH /scores/{score_id}", body,
                               lambda svc, connection, actor: assessment.revise_score(svc, connection, str(score_id), body, actor), interview_id=identity, report=True)

    @router.patch("/api/interviews/{interview_id}/eligibility", tags=["assessment"], response_model=ReportDocument)
    def eligibility(request: Request, interview_id: UUID, body: GraduateInput) -> Response:
        return recruiter_write(request, f"PATCH /interviews/{interview_id}/eligibility", body,
                               lambda svc, connection, actor: assessment.verify_graduate(svc, connection, str(interview_id), body, actor), interview_id=str(interview_id), report=True, fresh=True)

    @router.post("/api/interviews/{interview_id}/review", tags=["assessment"], response_model=ReportDocument)
    def review(request: Request, interview_id: UUID, body: ReviewInput) -> Response:
        return recruiter_write(request, f"POST /interviews/{interview_id}/review", body,
                               lambda svc, connection, actor: assessment.review_report(svc, connection, str(interview_id), body, actor), interview_id=str(interview_id), report=True)

    @router.post("/api/interviews/{interview_id}/print", tags=["assessment"])
    def print_report(request: Request, interview_id: UUID, body: PrintInput) -> Response:
        def work(svc: Service, connection: StorageSession, actor: Actor) -> Result:
            document = assessment.report_document(svc, connection, str(interview_id))
            if document["revision"] != body.expected_revision:
                raise DomainError("RESOURCE_CONFLICT", "报告已更新，请刷新后打印")
            svc.audit(connection, "report.print_requested", str(interview_id), {"revision": body.expected_revision}, actor, str(interview_id))
            return Result({"ok": True})
        return recruiter_write(request, f"POST /interviews/{interview_id}/print", body, work, interview_id=str(interview_id))

    return router
