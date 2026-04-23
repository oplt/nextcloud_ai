from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from backend.schemas.common_schema import ORMBaseSchema, TimestampedSchema


class RoleRead(ORMBaseSchema):
    id: UUID
    name: str
    description: str | None = None
    is_system: bool


class UserSummaryRead(ORMBaseSchema):
    id: UUID
    username: str
    email: EmailStr | None = None
    full_name: str | None = None


class UserBase(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, max_length=255)
    job_title: str | None = Field(default=None, max_length=255)


class UserCreate(UserBase):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=10, max_length=128)
    role_id: UUID | None = None
    is_superuser: bool = False


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    job_title: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = None
    is_active: bool | None = None
    role_id: UUID | None = None


class UserRead(TimestampedSchema):
    auth_provider: str
    external_subject: str | None = None
    username: str
    email: EmailStr | None = None
    full_name: str | None = None
    nextcloud_base_url: str | None = None
    last_login_at: datetime | None = None
    is_active: bool
    is_superuser: bool
    job_title: str | None = None
    avatar_url: str | None = None
    role: RoleRead | None = None
