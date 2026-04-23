from __future__ import annotations

from datetime import datetime
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


class ChatMemoryPatchRequest(BaseModel):
    clear: bool = False
    focus_lock_document_ids: list[str] | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)


class RetrievalFilters(BaseModel):
    connector_ids: list[UUID] = Field(default_factory=list)
    mime_types: list[str] = Field(default_factory=list)
    path_prefixes: list[str] = Field(default_factory=list)
    modified_after: datetime | None = None
    modified_before: datetime | None = None


class ChatAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=10000)
    top_k: int = Field(default=6, ge=1, le=20)
    session_id: UUID | None = None
    document_ids: list[UUID] | None = None
    parent_message_id: str | None = None
    request_id: str | None = None
    active_context_document_ids: list[str] = Field(default_factory=list)
    retrieval_filters: RetrievalFilters | None = None
    clear_session_memory: bool = False
    focus_lock_document_ids: list[str] = Field(default_factory=list)
    memory_items_patch: list[dict[str, Any]] | None = None


class ChatMessageRead(TimestampedSchema):
    session_id: UUID
    role: str
    content: str
    citations_json: list[dict] | None = None
    model_name: str | None = None
    generation_metadata_json: dict[str, Any] | None = None


class ChatSessionRead(TimestampedSchema):
    user_id: UUID
    title: str
    subject: str
    memory_json: dict[str, Any] | None = None


class ChatSessionDetail(ChatSessionRead):
    messages: list[ChatMessageRead]
    active_context_document_ids: list[str] = Field(default_factory=list)
    active_context_documents: list[dict[str, str]] = Field(default_factory=list)


class ChatAskResponse(BaseModel):
    session_id: UUID
    answer: str
    answer_confidence: float | None = None
    sources: list[ChatSource]
    user_message_id: UUID
    assistant_message_id: UUID
    parent_message_id: str | None
    request_id: str | None
    cited_sources: list[ChatSource]
    active_context_document_ids: list[str]
    active_context_documents: list[dict[str, str]]
    conversation_query: str
    generation_trace_id: str
    llm_provider: str
    llm_model_id: str
    grounded_prompt_version: str
    retrieval_settings: dict[str, Any] = Field(default_factory=dict)
    verification: dict[str, Any] | None = None
    retrieval_debug: dict[str, Any] | None = None
    memory_applied: dict[str, Any] | None = None

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
