from __future__ import annotations

import asyncio

from ..core.config import settings
from ..core.security import get_password_hash
from ..db.models import User
from ..db.repo.user import UserRepository
from ..db.session import AsyncSessionLocal
from ..services.role_bootstrap_service import RoleBootstrapService


async def main() -> None:
    async with AsyncSessionLocal() as session:
        repo = UserRepository(session)
        roles = await RoleBootstrapService(session).ensure_system_roles()
        existing = await repo.get_by_email(settings.FIRST_SUPERUSER_EMAIL)
        if existing:
            print("Admin already exists")
            return

        user = User(
            auth_provider="local",
            username=settings.FIRST_SUPERUSER_EMAIL,
            email=settings.FIRST_SUPERUSER_EMAIL,
            hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
            full_name="System Admin",
            is_active=True,
            is_superuser=True,
            role_id=roles["admin"].id,
        )
        await repo.add(user)
        await session.commit()
        print("Admin created")


if __name__ == "__main__":
    asyncio.run(main())
