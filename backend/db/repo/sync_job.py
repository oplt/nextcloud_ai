from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import SyncJob
from backend.db.repo.base import BaseRepository


class SyncJobRepository(BaseRepository[SyncJob]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SyncJob)

    async def get_by_job_key(self, job_key: str) -> SyncJob | None:
        result = await self.session.execute(
            select(SyncJob).where(SyncJob.job_key == job_key)
        )
        return result.scalar_one_or_none()

    async def list_by_connector(
        self, connector_id: UUID | str, *, offset: int = 0, limit: int = 100
    ) -> list[SyncJob]:
        result = await self.session.execute(
            select(SyncJob)
            .where(SyncJob.connector_id == connector_id)
            .order_by(SyncJob.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_latest_for_connector(
        self, connector_id: UUID | str
    ) -> SyncJob | None:
        result = await self.session.execute(
            select(SyncJob)
            .where(SyncJob.connector_id == connector_id)
            .order_by(SyncJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
