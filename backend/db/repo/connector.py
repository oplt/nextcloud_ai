from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.models import Connector
from backend.db.repo.base import BaseRepository


class ConnectorRepository(BaseRepository[Connector]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Connector)

    async def list_active(self) -> list[Connector]:
        result = await self.session.execute(
            select(Connector)
            .options(selectinload(Connector.owner))
            .where(Connector.is_active.is_(True))
            .order_by(Connector.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_visible_to_user(
        self,
        *,
        user_id: str,
        include_unowned: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Connector]:
        stmt = (
            select(Connector)
            .options(selectinload(Connector.owner))
            .order_by(Connector.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if not include_unowned:
            stmt = stmt.where(Connector.owner_user_id == user_id)
        else:
            stmt = stmt.where(
                or_(Connector.owner_user_id == user_id, Connector.owner_user_id.is_(None))
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_with_documents(self, connector_id: str) -> Connector | None:
        result = await self.session.execute(
            select(Connector)
            .options(selectinload(Connector.documents), selectinload(Connector.owner))
            .where(Connector.id == connector_id)
        )
        return result.scalar_one_or_none()

    async def get_active_by_base_url_and_username(
        self, *, base_url: str, username: str
    ) -> Connector | None:
        result = await self.session.execute(
            select(Connector).where(
                Connector.base_url == base_url.rstrip("/"),
                Connector.username == username,
                Connector.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()
