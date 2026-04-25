from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .common_schema import TimestampedSchema
from .intelligence_schema import (
    DocumentInsightRead,
    KnowledgeEdgeRead,
    KnowledgeNodeRead,
    WorkflowTaskRead,
)


_INTERNAL_METADATA_KEYS = {
    "stored_payload_b64",
}


def _sanitize_metadata(metadata_json: dict[str, Any] | None) -> dict[str, Any] | None:
    if metadata_json is None:
        return None
    return {
        key: value
        for key, value in metadata_json.items()
        if key not in _INTERNAL_METADATA_KEYS
    }


class DocumentChunkRead(TimestampedSchema):
    document_id: UUID
    chunk_index: int
    content: str
    token_count: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    page_number: int | None = None
    section_title: str | None = None
    heading_path: str | None = None
    content_hash: str | None = None
    chunk_type: str = "text"
    embedding_status: str = "pending"
    embedding_model: str | None = None
    metadata_json: dict[str, Any] | None = None


class DocumentRead(TimestampedSchema):
    connector_id: UUID | None = None
    external_id: str | None = None
    file_path: str
    file_name: str
    file_extension: str | None = None
    mime_type: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    source_type: str = "nextcloud"
    version_tag: str | None = None
    source_url: str | None = None
    modified_at: datetime | None = None
    sync_status: str
    sync_error: str | None = None
    parse_status: str
    parse_error: str | None = None
    language: str | None = None
    page_count: int | None = None
    word_count: int | None = None
    token_count: int | None = None
    indexed_at: datetime | None = None
    classified_at: datetime | None = None
    last_seen_at: datetime | None = None
    is_deleted: bool
    owner_external_id: str | None = None
    owner_id: UUID | None = None
    permission_scope: str | None = None
    allowed_user_ids: list[str]
    allowed_group_ids: list[str]
    public_link_enabled: bool
    acl_json: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None
    intelligence_json: dict[str, Any] | None = None
    ingestion_events_json: list[dict[str, Any]] | None = None
    document_type: str = "unclassified"
    document_type_confidence: float = 0.0
    document_type_reason: str | None = None
    document_type_source: str = "fallback"
    business_domain: str = "unknown"
    business_domain_confidence: float = 0.0
    business_domain_reason: str | None = None
    business_domain_source: str = "fallback"
    manual_category_override: bool = False
    chunk_count: int = 0
    signal_counts: dict[str, int] = Field(default_factory=dict)
    needs_review: bool = False

    @field_validator("metadata_json", mode="before")
    @classmethod
    def sanitize_metadata_json(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        return _sanitize_metadata(value)


class DocumentDetail(DocumentRead):
    chunks: list[DocumentChunkRead] = []
    insights: list[DocumentInsightRead] = []
    workflow_tasks: list[WorkflowTaskRead] = []
    knowledge_nodes: list[KnowledgeNodeRead] = []
    knowledge_edges: list[KnowledgeEdgeRead] = []


class DocumentClassificationPatch(BaseModel):
    document_type: str
    business_domain: str
    document_type_reason: str | None = None
    business_domain_reason: str | None = None


class DocumentTaxonomyRead(BaseModel):
    document_types: list[str]
    business_domains: list[str]
    parse_statuses: list[str]
