from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from backend.schemas.common_schema import TimestampedSchema


class ConnectorCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    base_url: str
    username: str = Field(min_length=1, max_length=255)
    secret: str = Field(min_length=1)
    root_path: str = "/"


class ConnectorUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    secret: str | None = None
    root_path: str | None = None
    is_active: bool | None = None
    status: str | None = None


class ConnectorRead(TimestampedSchema):
    connector_type: str
    display_name: str
    base_url: str
    username: str
    root_path: str
    is_active: bool
    status: str
    last_sync_at: datetime | None = None
    last_error: str | None = None