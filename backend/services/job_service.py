from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.exceptions import NotFoundError
from backend.db.models import SyncJob, User
from backend.db.repo.connector import ConnectorRepository
from backend.db.repo.sync_job import SyncJobRepository
from backend.services.job_lifecycle import JobLifecycleService


class JobService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SyncJobRepository(session)
        self.connector_repo = ConnectorRepository(session)

    async def create_sync_job(
        self,
        *,
        connector_id: str,
        requested_by: User | None,
        full_reindex: bool,
        job_key: str | None = None,
    ) -> SyncJob:
        connector = await self.connector_repo.get(connector_id)
        if connector is None:
            raise NotFoundError("Connector not found")
        effective_job_key = job_key or f"sync:{connector_id}:{uuid.uuid4()}"
        existing = await self.repo.get_by_job_key(effective_job_key)
        if existing is not None:
            return existing
        job = SyncJob(
            connector_id=connector.id,
            requested_by_id=requested_by.id if requested_by else None,
            job_key=effective_job_key,
            job_type="reindex" if full_reindex else "sync",
            status="queued",
            payload_json={"full_reindex": full_reindex},
        )
        await self.repo.add(job, flush=True)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def list_jobs(
        self, connector_id: str | None = None, *, limit: int = 100
    ) -> list[SyncJob]:
        if connector_id:
            return await self.repo.list_by_connector(connector_id, limit=limit)
        return await self.repo.list(limit=limit, order_by=SyncJob.created_at.desc())

    async def get_job(self, job_id: str) -> SyncJob:
        job = await self.repo.get(job_id)
        if job is None:
            raise NotFoundError("Job not found")
        return job

    async def mark_running(self, job: SyncJob, task_id: str | None = None) -> SyncJob:
        JobLifecycleService.mark_running(job, task_id=task_id)
        await self.session.commit()
        return job
