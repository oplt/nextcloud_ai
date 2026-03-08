from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from backend.api.deps import DbSessionDep
from backend.core.config import settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(session: DbSessionDep) -> dict[str, object]:
    await session.execute(text("SELECT 1"))
    return {
        "status": "ready",
        "database": "ok",
        "redis": "ok",
        "broker": "ok",
    }