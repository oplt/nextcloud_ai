from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.models import Connector, SyncJob
from backend.db.repo.base import BaseRepository


class SyncJobRepository(BaseRepository[SyncJob]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SyncJob)

    async def get_by_job_key(self, job_key: str) -> SyncJob | None:
        result = await self.session.execute(
            select(SyncJob)
            .options(selectinload(SyncJob.connector))
            .where(SyncJob.job_key == job_key)
        )
        return result.scalar_one_or_none()

    async def list_by_connector(
        self, connector_id: UUID | str, *, offset: int = 0, limit: int = 100
    ) -> list[SyncJob]:
        result = await self.session.execute(
            select(SyncJob)
            .options(selectinload(SyncJob.connector))
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
            .options(selectinload(SyncJob.connector))
            .where(SyncJob.connector_id == connector_id)
            .order_by(SyncJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_visible_to_user(
        self,
        *,
        user_id: UUID | str,
        connector_id: UUID | str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[SyncJob]:
        stmt = (
            select(SyncJob)
            .join(SyncJob.connector)
            .options(selectinload(SyncJob.connector))
            .where(
                or_(
                    SyncJob.requested_by_id == user_id,
                    Connector.owner_user_id == user_id,
                )
            )
            .order_by(SyncJob.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if connector_id:
            stmt = stmt.where(SyncJob.connector_id == connector_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())
