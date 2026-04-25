from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import AuthenticatedUser, DbSessionDep, permission_required
from ...schemas.job_schema import SyncJobRead
from ...services.job_service import JobService
from ...workers.indexing_tasks import enqueue_connector_sync_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[SyncJobRead])
async def list_jobs(
    session: DbSessionDep,
    identity: AuthenticatedUser = Depends(permission_required("jobs:read")),
    connector_id: str | None = Query(default=None),
) -> list[SyncJobRead]:
    jobs = await JobService(session).list_jobs_for_actor(
        actor=identity.user, connector_id=connector_id
    )
    return [SyncJobRead.model_validate(job) for job in jobs]


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
