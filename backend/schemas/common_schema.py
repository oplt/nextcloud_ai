from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ORMBaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TimestampedSchema(ORMBaseSchema):
    id: UUID
    created_at: datetime
    updated_at: datetime
