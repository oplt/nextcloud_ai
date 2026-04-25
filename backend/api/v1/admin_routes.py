from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import AuthenticatedUser, DbSessionDep, permission_required
from ...db.repo.audit_log import AuditLogRepository
from ...db.repo.user import RoleRepository
from ...schemas.admin_schema import AuditLogRead, RoleListResponse

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/roles", response_model=list[RoleListResponse])
async def list_roles(
    session: DbSessionDep,
    _: AuthenticatedUser = Depends(permission_required("roles:read")),
) -> list[RoleListResponse]:
    roles = await RoleRepository(session).list(limit=20)
    return [RoleListResponse.model_validate(role) for role in roles]


@router.get("/audit-logs", response_model=list[AuditLogRead])
async def list_audit_logs(
    session: DbSessionDep,
    _: AuthenticatedUser = Depends(permission_required("audit:read")),
    user_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    resource_id: str | None = Query(default=None),
    query: str | None = Query(default=None),
) -> list[AuditLogRead]:
    logs = await AuditLogRepository(session).search(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        query=query,
        limit=200,
    )
    return [AuditLogRead.model_validate(entry) for entry in logs]
