"""Retention cleanup Celery task — dry-run by default; covers proctor_logs via erase paths."""
from __future__ import annotations

from typing import cast

from interviewer.auth import Actor
from interviewer.contracts import Object
from interviewer.governance import retention_cleanup_batch
from interviewer.main import create_app
from interviewer.settings import Settings
from interviewer.tenancy import DEFAULT_TENANT_ID, reset_current_tenant, set_current_tenant
from interviewer.workers.celery_app import celery_app


@celery_app.task(name="interviewer.workers.tasks_cleanup.run_retention_cleanup")
def run_retention_cleanup(dry_run: bool = True, tenant_id: str | None = None) -> Object:
    """Select expired rows; when dry_run=False, erase via governance (includes proctor_logs)."""
    settings = Settings.from_env()
    app = create_app(settings)
    service = app.state.service
    service.database.migrate()
    actor = Actor("admin", "celery-cleanup", "Celery 保留期清理", tenant_id or DEFAULT_TENANT_ID)
    token = set_current_tenant(actor.tenant_id)
    try:
        with service.database.unit_of_work() as connection:
            return cast(Object, retention_cleanup_batch(
                service, connection, actor, dry_run=dry_run,
                reason="celery scheduled retention cleanup",
            ))
    finally:
        reset_current_tenant(token)
        service.database.close()
