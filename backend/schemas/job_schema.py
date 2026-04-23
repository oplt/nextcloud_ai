from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from backend.schemas.common_schema import TimestampedSchema
from backend.schemas.connector_schema import ConnectorRead


class SyncJobRead(TimestampedSchema):
    connector_id: UUID
    requested_by_id: UUID | None = None
    job_key: str
    worker_task_id: str | None = None
    job_type: str
    status: str
    retry_count: int
    progress_total: int | None = None
    progress_completed: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    payload_json: dict[str, Any] | None = None
    result_json: dict[str, Any] | None = None
    connector: ConnectorRead | None = None
