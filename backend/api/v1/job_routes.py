from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import AuthenticatedUser, DbSessionDep, permission_required
from ...schemas.job_schema import SyncJobListRead, SyncJobRead
from ...services.job_service import JobService
from ...workers.indexing_tasks import enqueue_connector_sync_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=SyncJobListRead)
async def list_jobs(
    session: DbSessionDep,
    identity: AuthenticatedUser = Depends(permission_required("jobs:read")),
    connector_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> SyncJobListRead:
    result = await JobService(session).list_jobs_page_for_actor(
        actor=identity.user,
        connector_id=connector_id,
        page=page,
        page_size=page_size,
    )
    return SyncJobListRead(
        items=[SyncJobRead.model_validate(job) for job in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("/{job_id}", response_model=SyncJobRead)
async def get_job(
    job_id: str,
    session: DbSessionDep,
    identity: AuthenticatedUser = Depends(permission_required("jobs:read")),
) -> SyncJobRead:
    job = await JobService(session).get_job_for_actor(job_id, actor=identity.user)
    return SyncJobRead.model_validate(job)


@router.post("/{job_id}/retry", response_model=SyncJobRead)
async def retry_job(
    job_id: str,
    session: DbSessionDep,
    identity: AuthenticatedUser = Depends(permission_required("jobs:retry_owned")),
) -> SyncJobRead:
    job_service = JobService(session)
    job = await job_service.retry_job(job_id, actor=identity.user)
    task = enqueue_connector_sync_job(str(job.id))
    job.worker_task_id = task.id
    await session.commit()
    await session.refresh(job)
    return SyncJobRead.model_validate(job)
