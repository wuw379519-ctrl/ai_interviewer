"""Job and competency routes (tags: jobs)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import Response

from interviewer.modules.common import recruiter_write, service_of
from interviewer.service import Result

from .schemas import CompetencySet, EmptyInput, JobCreate, Object


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/jobs", tags=["jobs"])
    def list_jobs(request: Request) -> Object:
        service = service_of(request)
        with service.database.unit_of_work() as connection:
            return service.dashboard(connection)

    @router.post("/api/jobs", tags=["jobs"], status_code=201)
    def create_job(request: Request, body: JobCreate) -> Response:
        return recruiter_write(request, "POST /jobs", body, lambda svc, connection, actor: svc.create_job(connection, body, actor))

    @router.post("/api/jobs/{job_id}/competencies:extract", tags=["jobs"])
    def extract(request: Request, job_id: UUID, body: EmptyInput) -> Response:
        return recruiter_write(request, f"POST /jobs/{job_id}/competencies:extract", body,
                               lambda svc, connection, actor: svc.extract_competencies(connection, str(job_id), actor))

    @router.patch("/api/jobs/{job_id}/competencies", tags=["jobs"])
    def confirm(request: Request, job_id: UUID, body: CompetencySet) -> Response:
        return recruiter_write(request, f"PATCH /jobs/{job_id}/competencies", body,
                               lambda svc, connection, actor: Result(svc.save_competencies(connection, str(job_id), body, True, actor)))

    return router
