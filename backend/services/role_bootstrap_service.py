from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Role
from ..db.repo.user import RoleRepository
from .authorization_service import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER


SYSTEM_ROLE_DESCRIPTIONS: dict[str, str] = {
    ROLE_ADMIN: "Full administrative access across users, connectors, jobs, and audit logs.",
    ROLE_OPERATOR: "Can manage owned connectors, review jobs, reindex documents, and use chat.",
    ROLE_VIEWER: "Read-only access for visible documents and grounded chat.",
}


class RoleBootstrapService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = RoleRepository(session)

    async def ensure_system_roles(self) -> dict[str, Role]:
        roles: dict[str, Role] = {}
        for name, description in SYSTEM_ROLE_DESCRIPTIONS.items():
            role = await self.repo.get_by_name(name)
            if role is None:
                role = Role(name=name, description=description, is_system=True)
                await self.repo.add(role, flush=True)
            elif role.is_system and role.description != description:
                role.description = description
            roles[name] = role
        return roles
