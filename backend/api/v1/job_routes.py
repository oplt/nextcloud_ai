from __future__ import annotations

from fastapi import APIRouter, Query

from backend.api.deps import CurrentIdentityDep, DbSessionDep
from backend.schemas.job_schema import SyncJobRead
from backend.services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/", response_model=list[SyncJobRead])
async def list_jobs(
    session: DbSessionDep,
    _: CurrentIdentityDep,
    connector_id: str | None = Query(default=None),
) -> list[SyncJobRead]:
    jobs = await JobService(session).list_jobs(connector_id=connector_id)
    return [SyncJobRead.model_validate(job) for job in jobs]


@router.get("/{job_id}", response_model=SyncJobRead)
async def get_job(job_id: str, session: DbSessionDep, _: CurrentIdentityDep) -> SyncJobRead:
    job = await JobService(session).get_job(job_id)
    return SyncJobRead.model_validate(job)
