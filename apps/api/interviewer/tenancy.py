"""Tenant context helpers. Tenant is resolved from auth, never from client input."""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

from fastapi import Request
from sqlalchemy import ColumnElement, Table

from .errors import DomainError

if TYPE_CHECKING:
    from .auth import Actor

# Fixed default workspace tenant — migrations seed this id; do not regenerate.
# Canonical dashed UUID strings (String columns — avoid SQLAlchemy Uuid dash-stripping).
DEFAULT_TENANT_ID = "00000000-0000-4000-8000-000000000001"
DEFAULT_TENANT_NAME = "default"
DEFAULT_ADMIN_USER_ID = "00000000-0000-4000-8000-000000000011"
DEFAULT_RECRUITER_USER_ID = "00000000-0000-4000-8000-000000000012"
DEFAULT_ADMIN_BINDING_ID = "00000000-0000-4000-8000-000000000021"
DEFAULT_RECRUITER_BINDING_ID = "00000000-0000-4000-8000-000000000022"

_current_tenant: ContextVar[str | None] = ContextVar("app_tenant_id", default=None)

# Business tables with a tenant_id column that list/get paths must scope.
TENANT_SCOPED_TABLES = frozenset({
    "jobs", "candidates", "competencies", "interviews", "questions", "turns", "evidence",
    "scores", "score_revisions", "reports", "consents", "resumes", "idempotency_keys",
    "data_policies", "audit_logs", "interview_events", "practice_sessions", "proctor_logs",
})


def set_current_tenant(tenant_id: str) -> Token[str | None]:
    return _current_tenant.set(str(tenant_id))


def reset_current_tenant(token: Token[str | None]) -> None:
    _current_tenant.reset(token)


def current_tenant() -> str:
    value = _current_tenant.get()
    return str(value) if value else DEFAULT_TENANT_ID


def get_current_tenant(request: Request) -> str:
    """Return the authenticated actor's tenant; fall back to default for unscoped system paths."""
    from .auth import Actor

    actor = getattr(request.state, "actor", None)
    if isinstance(actor, Actor) and actor.tenant_id:
        return str(actor.tenant_id)
    return DEFAULT_TENANT_ID


def get_current_user(request: Request) -> Actor:
    from .auth import Actor

    actor = getattr(request.state, "actor", None)
    if not isinstance(actor, Actor):
        raise DomainError("UNAUTHORIZED", "请先完成身份验证")
    return actor


def tenant_clause(table: Table) -> ColumnElement[bool] | None:
    """Equality filter for tables that carry tenant_id; None if the table is not scoped."""
    if table.name not in TENANT_SCOPED_TABLES or "tenant_id" not in table.c:
        return None
    return table.c.tenant_id == current_tenant()


def row_tenant_id(row: dict[str, object]) -> str | None:
    if "tenant_id" in row and row["tenant_id"] is not None:
        return str(row["tenant_id"])
    if "tenant" in row and row["tenant"] is not None:
        return str(row["tenant"])
    return None


def ensure_tenant_row(row: dict[str, object] | None, code: str, message: str = "请求的资料不存在") -> None:
    """Raise the same not-found error for missing or cross-tenant rows (no existence leak)."""
    if row is None:
        raise DomainError(code, message)
    owned = row_tenant_id(row)
    if owned is not None and owned != current_tenant():
        raise DomainError(code, message)


def bind_tenant_guc_sql() -> str:
    """Documented GUC name used by PG RLS policies and Database.transaction SET LOCAL."""
    return "app.tenant_id"
