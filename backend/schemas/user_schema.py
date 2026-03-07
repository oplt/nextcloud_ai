from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from backend.schemas.common_schema import ORMBaseSchema, TimestampedSchema


class RoleRead(ORMBaseSchema):
    id: UUID
    name: str
    description: str | None = None
    is_system: bool


class UserBase(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)
    job_title: str | None = Field(default=None, max_length=255)


class UserCreate(UserBase):
    password: str = Field(min_length=10, max_length=128)
    role_id: UUID | None = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    job_title: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = None
    is_active: bool | None = None
    role_id: UUID | None = None


class UserRead(TimestampedSchema):
    email: EmailStr
    full_name: str | None = None
    is_active: bool
    is_superuser: bool
    job_title: str | None = None
    avatar_url: str | None = None
    role: RoleRead | None = None


class UserPublic(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str | None = None