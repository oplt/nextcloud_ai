from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import AuthenticatedUser, DbSessionDep, permission_required
from ...schemas.intelligence_schema import IntelligenceOverviewRead
from ...services.product_intelligence_service import ProductIntelligenceService

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


@router.get("/overview", response_model=IntelligenceOverviewRead)
async def get_intelligence_overview(
    session: DbSessionDep,
    identity: AuthenticatedUser = Depends(permission_required("documents:read")),
) -> IntelligenceOverviewRead:
    return await ProductIntelligenceService(session).build_overview(auth=identity.auth)
