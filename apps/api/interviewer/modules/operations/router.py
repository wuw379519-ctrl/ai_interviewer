"""Health and readiness routes (tags: operations)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from interviewer import database as db
from interviewer.errors import DomainError
from interviewer.modules.common import send, service_of
from interviewer.service import Result

from .schemas import Object


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/health", tags=["operations"])
    def health(request: Request) -> Object:
        service = service_of(request)
        settings = service.settings
        database = service.database
        return {"ok": True, "service": "aii-python", "version": "1.0.0",
                "instanceId": str(request.app.state.instance_id), "llmProvider": settings.provider,
                "demoMode": settings.demo, "dbDriver": "postgres" if database.postgres else "sqlite",
                "timestamp": db.iso(db.now())}

    @router.get("/api/ready", tags=["operations"])
    def ready(request: Request) -> Response:
        service = service_of(request)
        settings = service.settings
        database = service.database
        issues = settings.deployment_issues()
        if issues:
            raise DomainError("NOT_READY", "部署配置尚未就绪", {"issues": issues})
        try:
            with database.unit_of_work() as connection:
                service.policy(connection)
        except Exception as error:
            raise DomainError("NOT_READY", "数据库或迁移尚未就绪") from error
        return send(Result({"ok": True, "database": "ready", "mode": settings.environment,
                            "speech": "server_configured" if settings.stt_provider == "whisper" or settings.stt_base_url and settings.stt_model else "device_local"}))

    return router
