from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.exceptions import AuthorizationError, NotFoundError
from backend.db.models import SyncJob, User
from backend.db.repo.connector import ConnectorRepository
from backend.db.repo.sync_job import SyncJobRepository
from backend.services.authorization_service import connector_is_manageable_by_identity
from backend.services.job_lifecycle import JobLifecycleService
from backend.services.connector_service import _user_to_auth


@dataclass(slots=True)
class SyncJobReservation:
    job: SyncJob
    created: bool


class JobService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SyncJobRepository(session)
        self.connector_repo = ConnectorRepository(session)

    async def reserve_sync_job(
        self,
        *,
        connector_id: str,
        requested_by: User | None,
        full_reindex: bool,
        job_key: str | None = None,
        payload_json: dict | None = None,
    ) -> SyncJobReservation:
        connector = await self.connector_repo.get(connector_id)
        if connector is None:
            raise NotFoundError("Connector not found")
        effective_job_key = job_key or f"sync:{connector_id}:{uuid.uuid4()}"
        existing = await self.repo.get_by_job_key(effective_job_key)
        if existing is not None:
            return SyncJobReservation(job=existing, created=False)

        job_payload = {"full_reindex": full_reindex}
        if payload_json:
            job_payload.update(payload_json)

        job = SyncJob(
            connector_id=connector.id,
            requested_by_id=requested_by.id if requested_by else None,
            job_key=effective_job_key,
            job_type="reindex" if full_reindex else "sync",
            status="queued",
            payload_json=job_payload,
        )
        await self.repo.add(job, flush=True)
        await self.session.commit()
        await self.session.refresh(job)
        return SyncJobReservation(job=job, created=True)

    async def create_sync_job(
        self,
        *,
        connector_id: str,
        requested_by: User | None,
        full_reindex: bool,
        job_key: str | None = None,
        payload_json: dict | None = None,
    ) -> SyncJob:
        reservation = await self.reserve_sync_job(
            connector_id=connector_id,
            requested_by=requested_by,
            full_reindex=full_reindex,
            job_key=job_key,
            payload_json=payload_json,
        )
        return reservation.job

    async def list_jobs(
        self, connector_id: str | None = None, *, limit: int = 100
    ) -> list[SyncJob]:
        if connector_id:
            return await self.repo.list_by_connector(connector_id, limit=limit)
        return await self.repo.list(limit=limit, order_by=SyncJob.created_at.desc())

    async def list_jobs_for_actor(
        self, *, actor: User, connector_id: str | None = None, limit: int = 100
    ) -> list[SyncJob]:
        actor_auth = _user_to_auth(actor)
        if actor_auth.is_superuser:
            return await self.list_jobs(connector_id=connector_id, limit=limit)
        return await self.repo.list_visible_to_user(
            user_id=actor.id, connector_id=connector_id, limit=limit
        )

    async def get_job(self, job_id: str) -> SyncJob:
        job = await self.repo.get(job_id)
        if job is None:
            raise NotFoundError("Job not found")
        return job

    async def get_job_for_actor(self, job_id: str, *, actor: User) -> SyncJob:
        job = await self.get_job(job_id)
        if job.connector is None:
            connector = await self.connector_repo.get(job.connector_id)
            job.connector = connector
        actor_auth = _user_to_auth(actor)
        if actor_auth.is_superuser:
            return job
        if job.requested_by_id == actor.id:
            return job
        if (
            job.connector is None
            or not connector_is_manageable_by_identity(
                job.connector, auth=actor_auth, user=actor
            )
        ):
            raise AuthorizationError("Job is not assigned to you")
        return job

    async def retry_job(self, job_id: str, *, actor: User) -> SyncJob:
        job = await self.get_job_for_actor(job_id, actor=actor)
        if job.status not in {"failed", "dead_lettered"}:
            raise AuthorizationError("Only failed jobs can be retried")
        payload_json = dict(job.payload_json or {})
        reservation = await self.reserve_sync_job(
            connector_id=str(job.connector_id),
            requested_by=actor,
            full_reindex=bool(payload_json.get("full_reindex", False)),
            job_key=f"retry:{job.id}:{uuid.uuid4()}",
            payload_json={
                **payload_json,
                "trigger": "manual_retry",
                "retry_of_job_id": str(job.id),
            },
        )
        return reservation.job

    async def mark_running(self, job: SyncJob, task_id: str | None = None) -> SyncJob:
        JobLifecycleService.mark_running(job, task_id=task_id)
        await self.session.commit()
        return job
