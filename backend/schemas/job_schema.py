from __future__ import annotations

from datetime import datetime
from uuid import UUID

from backend.schemas.common_schema import TimestampedSchema


class SyncJobRead(TimestampedSchema):
    connector_id: UUID
    job_type: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    payload_json: dict | None = None
    result_json: dict | None = None