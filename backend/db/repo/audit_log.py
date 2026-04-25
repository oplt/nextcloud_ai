from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import AuditLog
from ..repo.base import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AuditLog)

    async def list_for_user(
        self, user_id: UUID | str, *, offset: int = 0, limit: int = 100
    ) -> list[AuditLog]:
        result = await self.session.execute(
            select(AuditLog)
            .options(selectinload(AuditLog.user))
            .where(AuditLog.user_id == user_id)
            .order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def search(
        self,
        *,
        user_id: UUID | str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        query: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .options(selectinload(AuditLog.user))
            .order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if resource_type:
            stmt = stmt.where(AuditLog.resource_type == resource_type)
        if resource_id:
            stmt = stmt.where(AuditLog.resource_id == resource_id)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(
                    AuditLog.message.ilike(like),
                    AuditLog.resource_id.ilike(like),
                )
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
