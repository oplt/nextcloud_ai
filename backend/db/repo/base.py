from __future__ import annotations

from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeMeta

ModelT = TypeVar("ModelT")


class BaseRepository(Generic[ModelT]):
    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    async def add(self, instance: ModelT, *, flush: bool = False) -> ModelT:
        self.session.add(instance)
        if flush:
            await self.session.flush()
        return instance

    async def get(self, obj_id: UUID | str) -> ModelT | None:
        stmt = select(self.model).where(self.model.id == obj_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        order_by: Any | None = None,
    ) -> list[ModelT]:
        stmt = select(self.model).offset(offset).limit(limit)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        stmt = select(func.count()).select_from(self.model)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def delete(self, instance: ModelT, *, flush: bool = False) -> None:
        await self.session.delete(instance)
        if flush:
            await self.session.flush()

    async def delete_by_id(self, obj_id: UUID | str, *, flush: bool = False) -> int:
        stmt = delete(self.model).where(self.model.id == obj_id)
        result = await self.session.execute(stmt)
        if flush:
            await self.session.flush()
        return int(result.rowcount or 0)

    async def flush(self) -> None:
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    async def refresh(self, instance: ModelT) -> None:
        await self.session.refresh(instance)