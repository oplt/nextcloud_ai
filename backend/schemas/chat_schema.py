from __future__ import annotations

from typing import Any
from uuid import UUID
from dataclasses import dataclass, field
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
    heading_path: str | None = None
    content: str | None = Field(default=None, exclude=True, repr=False)


class ChatAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=10000)
    top_k: int = Field(default=6, ge=1, le=20)
    session_id: UUID | None = None
    document_ids: list[UUID] | None = None
    parent_message_id: str | None = None
    request_id: str | None = None
    active_context_document_ids: list[str] = Field(default_factory=list)


class ChatMessageRead(TimestampedSchema):
    session_id: UUID
    role: str
    content: str
    citations_json: list[dict] | None = None
    model_name: str | None = None


class ChatSessionRead(TimestampedSchema):
    user_id: UUID
    title: str
    subject: str


class ChatSessionDetail(ChatSessionRead):
    messages: list[ChatMessageRead]


class ChatAskResponse(BaseModel):
    session_id: UUID
    answer: str
    sources: list[ChatSource]
    user_message_id: UUID
    assistant_message_id: UUID
    parent_message_id: str | None
    request_id: str | None
    cited_sources: list[ChatSource]
    active_context_document_ids: list[str]
    active_context_documents: list[dict[str, str]]
    conversation_query: str

@dataclass(slots=True)
class ConversationState:
    session_id: str
    active_document_ids: list[str] = field(default_factory=list)
    last_cited_chunk_ids: list[str] = field(default_factory=list)
    retrieval_summary: str | None = None
    topic_fingerprint: str | None = None


@dataclass(slots=True)
class ChatTurn:
    message_id: str
    role: str
    content: str


@dataclass(slots=True)
class GroundedChunk:
    chunk_id: str
    document_id: str
    file_name: str
    file_path: str
    content: str
    score: float
    distance: float
    page_number: int | None = None
    section_title: str | None = None
    heading_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_source(self) -> ChatSource:
        return ChatSource(
            chunk_id=self.chunk_id,
            document_id=self.document_id,
            file_name=self.file_name,
            file_path=self.file_path,
            snippet=self.metadata.get('snippet', self.content[:240]),
            score=self.score,
            distance=self.distance,
            page_number=self.page_number,
            section_title=self.section_title,
            heading_path=self.heading_path,
            content=self.content,
        )
