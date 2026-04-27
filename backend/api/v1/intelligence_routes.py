from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import AuthenticatedUser, DbSessionDep, permission_required
from ...schemas.intelligence_schema import IntelligenceOverviewRead
from ...services.product_intelligence_service import ProductIntelligenceService

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


@router.get("/overview", response_model=IntelligenceOverviewRead)
async def get_intelligence_overview(
    session: DbSessionDep,
    identity: AuthenticatedUser = Depends(permission_required("documents:read")),
    task_search: str | None = Query(default=None),
    blocked_by_task_id: str | None = Query(default=None),
) -> IntelligenceOverviewRead:
    return await ProductIntelligenceService(session).build_overview(
        auth=identity.auth,
        task_search=task_search,
        blocked_by_task_id=blocked_by_task_id,
    )
