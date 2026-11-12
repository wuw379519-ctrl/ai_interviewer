"""Tenant context helpers. Tenant is resolved from auth, never from client input."""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

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
