from __future__ import annotations

from typing import Any
from uuid import UUID

from .common_schema import TimestampedSchema
from .user_schema import RoleRead, UserSummaryRead


class AuditLogRead(TimestampedSchema):
    user_id: UUID | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    message: str | None = None
    metadata_json: dict[str, Any] | None = None
    user: UserSummaryRead | None = None


class RoleListResponse(RoleRead):
    pass
