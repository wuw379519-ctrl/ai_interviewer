"""Async report generation — HTTP /score stays synchronous; enqueue this task for ops/async."""
from __future__ import annotations

from typing import cast

from interviewer import assessment
from interviewer.auth import Actor
from interviewer.contracts import Object
from interviewer.main import create_app
from interviewer.settings import Settings
from interviewer.tenancy import DEFAULT_TENANT_ID, reset_current_tenant, set_current_tenant
from interviewer.workers.celery_app import celery_app


@celery_app.task(name="interviewer.workers.tasks_report.generate_report_task")
def generate_report_task(
    interview_id: str,
    rerun: bool = False,
    actor_id: str = "celery-report",
    tenant_id: str | None = None,
) -> Object:
    """Run assessment.generate_report off the request path. Sync HTTP remains the fallback."""
    settings = Settings.from_env()
    app = create_app(settings)
    service = app.state.service
    service.database.migrate()
    actor = Actor("recruiter", actor_id, "Celery 报告生成", tenant_id or DEFAULT_TENANT_ID)
    token = set_current_tenant(actor.tenant_id)
    try:
        with service.database.unit_of_work() as connection:
            result = assessment.generate_report(service, connection, interview_id, rerun, actor)
            return cast(Object, result.payload)
    finally:
        reset_current_tenant(token)
        service.database.close()
