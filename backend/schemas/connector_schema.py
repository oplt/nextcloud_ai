from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from backend.schemas.common_schema import TimestampedSchema
from backend.schemas.user_schema import UserSummaryRead


class ConnectorCreate(BaseModel):
    connector_type: str = Field(default="nextcloud", pattern="^(nextcloud|imap)$")
    display_name: str = Field(min_length=1, max_length=255)
    base_url: str
    username: str = Field(min_length=1, max_length=255)
    secret: str = Field(min_length=1)
    root_path: str = "/"
    verify_tls: bool | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    use_ssl: bool | None = None
    search_criteria: str | None = Field(default=None, max_length=255)
    owner_user_id: UUID | None = None

    @model_validator(mode="after")
    def validate_root_path(self) -> "ConnectorCreate":
        if self.connector_type == "imap" and not self.root_path.strip():
            raise ValueError("IMAP connectors require a mailbox name in root_path")
        return self


class ConnectorUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    secret: str | None = None
    root_path: str | None = None
    is_active: bool | None = None
    status: str | None = None
    verify_tls: bool | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    use_ssl: bool | None = None
    search_criteria: str | None = Field(default=None, max_length=255)
    owner_user_id: UUID | None = None


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
    metadata_json: dict[str, Any] | None = None
    owner_user_id: UUID | None = None
    owner: UserSummaryRead | None = None


class ConnectorSyncRequest(BaseModel):
    full_reindex: bool = False
    idempotency_key: str | None = Field(default=None, max_length=255)


class ConnectorTestResponse(BaseModel):
    ok: bool
    message: str
