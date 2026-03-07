from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import SyncJob
from backend.repositories.base import BaseRepository


class SyncJobRepository(BaseRepository[SyncJob]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SyncJob)

    async def list_by_connector(
            self,
            connector_id: UUID | str,
            *,
            offset: int = 0,
            limit: int = 100,
    ) -> list[SyncJob]:
        stmt = (
            select(SyncJob)
            .where(SyncJob.connector_id == connector_id)
            .order_by(SyncJob.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_for_connector(
            self,
            connector_id: UUID | str,
    ) -> SyncJob | None:
        stmt = (
            select(SyncJob)
            .where(SyncJob.connector_id == connector_id)
            .order_by(SyncJob.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()