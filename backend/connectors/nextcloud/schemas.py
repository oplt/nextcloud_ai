from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DavNode(BaseModel):
    path: str
    href: str
    file_id: str | None = None
    etag: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    last_modified: datetime | None = None
    is_directory: bool = False


class ShareGrant(BaseModel):
    share_id: str = Field(validation_alias="id")
    share_type: int = Field(validation_alias="share_type")
    permissions: int
    path: str
    uid_owner: str | None = None
    share_with: str | None = None
    display_name_owner: str | None = None


class AccessControlEntry(BaseModel):
    path: str
    owner_user_id: str | None = None
    allowed_user_ids: list[str] = Field(default_factory=list)
    allowed_group_ids: list[str] = Field(default_factory=list)
    public_link_enabled: bool = False
    raw_shares: list[ShareGrant] = Field(default_factory=list)


class SyncBatchItem(BaseModel):
    node: DavNode
    acl: AccessControlEntry


class BridgeTokenClaims(BaseModel):
    iss: str
    aud: str
    sub: str
    preferred_username: str
    display_name: str | None = None
    email: str | None = None
    groups: list[str] = Field(default_factory=list)
    nc_base_url: str
    provider: Literal["nextcloud"] = "nextcloud"
    jti: str
    iat: int
    nbf: int
    exp: int


class BridgeExchangeRequest(BaseModel):
    bridge_token: str


class Principal(BaseModel):
    sub: str
    provider: Literal["nextcloud"] = "nextcloud"
    username: str
    display_name: str | None = None
    email: str | None = None
    groups: list[str] = Field(default_factory=list)
    nc_base_url: str


class BridgeExchangeResponse(BaseModel):
    expires_in: int
    principal: Principal


class NextcloudWebhookEvent(BaseModel):
    event: str
    connector_id: str | None = None
    subject: str | None = None
    path: str | None = None
    actor: str | None = None
    base_url: str | None = None
    username: str | None = None
    file_id: str | None = None
    is_directory: bool | None = None
    timestamp: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
