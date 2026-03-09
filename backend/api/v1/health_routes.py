from __future__ import annotations

import asyncio

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from backend.api.deps import DbSessionDep
from backend.services.health_service import HealthCheckService

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(session: DbSessionDep) -> JSONResponse:
    health_service = HealthCheckService()
    database_status, redis_status, broker_status, ai_runtime_status = await asyncio.gather(
        health_service.check_database(session),
        health_service.check_redis(),
        health_service.check_broker(),
        health_service.check_ai_runtime(),
    )

    response_status = status.HTTP_200_OK
    if not (
        database_status.ok
        and redis_status.ok
        and broker_status.ok
        and ai_runtime_status.ready
    ):
        response_status = status.HTTP_503_SERVICE_UNAVAILABLE

    payload = {
        "status": "ready"
        if response_status == status.HTTP_200_OK
        else "not_ready",
        "database": database_status.detail,
        "ai_runtime": ai_runtime_status.to_dict(),
        "redis": redis_status.detail,
        "broker": broker_status.detail,
    }
    return JSONResponse(status_code=response_status, content=payload)
