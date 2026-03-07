from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from backend.schemas.common_schema import TimestampedSchema


class ChatSource(BaseModel):
    chunk_id: UUID
    document_id: UUID
    file_name: str
    file_path: str
    page_number: int | None = None
    section_title: str | None = None
    snippet: str
    distance: float
    score: float


class ChatAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=10000)
    top_k: int = Field(default=6, ge=1, le=20)
    session_id: UUID | None = None
    document_ids: list[UUID] | None = None


class ChatMessageRead(TimestampedSchema):
    session_id: UUID
    role: str
    content: str
    retrieved_chunks_json: list[dict] | None = None
    model_name: str | None = None


class ChatSessionRead(TimestampedSchema):
    user_id: UUID
    title: str


class ChatAskResponse(BaseModel):
    session_id: UUID
    answer: str
    sources: list[ChatSource]
    user_message_id: UUID
    assistant_message_id: UUID