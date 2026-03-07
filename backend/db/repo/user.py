from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.models import Role, User
from backend.db.repo.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> User | None:
        stmt = (
            select(User)
            .options(selectinload(User.role))
            .where(User.email == email)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self, *, offset: int = 0, limit: int = 100) -> list[User]:
        stmt = (
            select(User)
            .options(selectinload(User.role))
            .where(User.is_active.is_(True))
            .order_by(User.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class RoleRepository(BaseRepository[Role]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Role)

    async def get_by_name(self, name: str) -> Role | None:
        stmt = select(Role).where(Role.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()