from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.models import Role, User
from backend.db.repo.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(
            select(User).options(selectinload(User.role)).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_by_external_subject(
        self, auth_provider: str, external_subject: str
    ) -> User | None:
        result = await self.session.execute(
            select(User)
            .options(selectinload(User.role))
            .where(
                User.auth_provider == auth_provider,
                User.external_subject == external_subject,
            )
        )
        return result.scalar_one_or_none()

    async def list_active(self, *, offset: int = 0, limit: int = 100) -> list[User]:
        result = await self.session.execute(
            select(User)
            .options(selectinload(User.role))
            .where(User.is_active.is_(True))
            .order_by(User.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def search(self, query: str | None = None, *, limit: int = 100) -> list[User]:
        stmt = (
            select(User)
            .options(selectinload(User.role))
            .order_by(User.created_at.desc())
            .limit(limit)
        )
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(
                    User.email.ilike(like),
                    User.username.ilike(like),
                    User.full_name.ilike(like),
                )
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class RoleRepository(BaseRepository[Role]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Role)

    async def get_by_name(self, name: str) -> Role | None:
        result = await self.session.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()
