from __future__ import annotations

from uuid import UUID

from datetime import datetime, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Connector, SyncJob
from .base import BaseRepository


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

    async def reset_stale_running_jobs(self, *, message: str) -> int:
        """Fail only jobs with an explicit expired lease.

        A missing lease is unknown/legacy state, not evidence that the worker is
        dead. In particular, API restarts must not fail such jobs blindly.
        """
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            update(SyncJob)
            .where(
                SyncJob.status.in_(("running", "retrying")),
                SyncJob.lease_expires_at.is_not(None),
                SyncJob.lease_expires_at < now,
            )
            .values(
                status="failed",
                completed_at=now,
                error_message=message,
                lease_expires_at=None,
            )
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    async def fail_expired_leases(self, *, message: str) -> int:
        """Same as reset_stale_running_jobs; explicit name for beat/API use."""
        return await self.reset_stale_running_jobs(message=message)

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

    async def count_by_connector(
        self, *, connector_id: UUID | str | None = None
    ) -> int:
        stmt = select(func.count()).select_from(SyncJob)
        if connector_id:
            stmt = stmt.where(SyncJob.connector_id == connector_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def count_visible_to_user(
        self,
        *,
        user_id: UUID | str,
        connector_id: UUID | str | None = None,
    ) -> int:
        stmt = (
            select(func.count(SyncJob.id))
            .select_from(SyncJob)
            .join(SyncJob.connector)
            .where(
                or_(
                    SyncJob.requested_by_id == user_id,
                    Connector.owner_user_id == user_id,
                )
            )
        )
        if connector_id:
            stmt = stmt.where(SyncJob.connector_id == connector_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())
