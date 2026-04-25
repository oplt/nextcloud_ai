from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from .common_schema import TimestampedSchema


class DocumentInsightRead(TimestampedSchema):
    document_id: UUID
    insight_type: str
    title: str | None = None
    summary: str | None = None
    status: str
    confidence: float | None = None
    owner_label: str | None = None
    due_at: datetime | None = None
    payload_json: dict[str, Any] | None = None


class WorkflowTaskRead(TimestampedSchema):
    document_id: UUID | None = None
    insight_id: UUID | None = None
    task_type: str
    queue_name: str
    title: str
    description: str | None = None
    status: str
    priority: str
    owner_label: str | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    hook_status: str | None = None
    hook_response: str | None = None
    hook_last_attempt_at: datetime | None = None
    metadata_json: dict[str, Any] | None = None


class KnowledgeNodeRead(TimestampedSchema):
    node_type: str
    label: str
    external_key: str
    document_id: UUID | None = None
    metadata_json: dict[str, Any] | None = None


class KnowledgeEdgeRead(TimestampedSchema):
    source_node_id: UUID
    target_node_id: UUID
    document_id: UUID | None = None
    relation_type: str
    weight: float
    metadata_json: dict[str, Any] | None = None


class IntelligenceOpenTaskRead(WorkflowTaskRead):
    document_file_name: str | None = None
    document_file_path: str | None = None
    document_connector_id: UUID | None = None


class IntelligenceSpotlightDocumentRead(BaseModel):
    document_id: UUID
    file_name: str
    file_path: str
    connector_id: UUID
    classification: str | None = None
    insight_types: list[str] = Field(default_factory=list)
    open_task_count: int = 0
    queue_names: list[str] = Field(default_factory=list)
    modified_at: datetime | None = None
    updated_at: datetime


class IntelligenceOverviewRead(BaseModel):
    intelligence_feature_enabled: bool = True
    wedge: str
    document_type_counts: dict[str, int] = Field(default_factory=dict)
    task_status_counts: dict[str, int] = Field(default_factory=dict)
    queue_counts: dict[str, int] = Field(default_factory=dict)
    open_tasks: list[IntelligenceOpenTaskRead] = Field(default_factory=list)
    spotlight_documents: list[IntelligenceSpotlightDocumentRead] = Field(
        default_factory=list
    )
