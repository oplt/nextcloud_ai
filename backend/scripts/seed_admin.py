from __future__ import annotations

import asyncio

from backend.core.config import settings
from backend.core.security import get_password_hash
from backend.db.models import User
from backend.db.repo.user import UserRepository
from backend.db.session import AsyncSessionLocal


async def main() -> None:
    async with AsyncSessionLocal() as session:
        repo = UserRepository(session)
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
        )
        await repo.add(user)
        await session.commit()
        print("Admin created")


if __name__ == "__main__":
    asyncio.run(main())
