from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AuditLog, User
from ..db.repo.audit_log import AuditLogRepository


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AuditLogRepository(session)

    async def log(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        message: str | None = None,
        metadata: dict | None = None,
        user: User | None = None,
        flush: bool = False,
    ) -> AuditLog:
        entry = AuditLog(
            user_id=user.id if user else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            message=message,
            metadata_json=metadata,
        )
        await self.repo.add(entry, flush=flush)
        return entry
