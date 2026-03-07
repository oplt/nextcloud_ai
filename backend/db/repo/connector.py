from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.models import Connector
from backend.db.repo.base import BaseRepository


class ConnectorRepository(BaseRepository[Connector]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Connector)

    async def list_active(self) -> list[Connector]:
        result = await self.session.execute(
            select(Connector).where(Connector.is_active.is_(True)).order_by(Connector.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_with_documents(self, connector_id: str) -> Connector | None:
        result = await self.session.execute(
            select(Connector)
            .options(selectinload(Connector.documents))
            .where(Connector.id == connector_id)
        )
        return result.scalar_one_or_none()
