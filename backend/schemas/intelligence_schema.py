from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

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
    confidence_level: str | None = None
    confidence_score: float | None = None
    evidence_method: str | None = None
    evidence_items: list[dict[str, Any]] = Field(default_factory=list)
    reason: str | None = None
    recommended_action: str | None = None
    review_status: str | None = None

    @model_validator(mode="after")
    def hydrate_validation_fields(self) -> "WorkflowTaskRead":
        meta = self.metadata_json or {}
        validation = meta.get("task_validation")
        validation_meta = validation if isinstance(validation, dict) else {}

        self.confidence_level = self.confidence_level or _string_meta(
            meta, validation_meta, "confidence_level"
        )
        self.confidence_score = self.confidence_score if self.confidence_score is not None else _float_meta(
            meta, validation_meta, "confidence_score"
        )
        self.evidence_method = self.evidence_method or _string_meta(
            meta, validation_meta, "evidence_method"
        )
        if not self.evidence_items:
            evidence_items = meta.get("evidence_items")
            self.evidence_items = evidence_items if isinstance(evidence_items, list) else []
        self.reason = self.reason or _string_meta(meta, validation_meta, "reason")
        self.recommended_action = self.recommended_action or _string_meta(
            meta, validation_meta, "recommended_action"
        )
        self.review_status = self.review_status or _string_meta(
            meta, validation_meta, "review_status", "status"
        )
        return self


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
    business_domain_counts: dict[str, int] = Field(default_factory=dict)
    task_status_counts: dict[str, int] = Field(default_factory=dict)
    queue_counts: dict[str, int] = Field(default_factory=dict)
    open_tasks: list[IntelligenceOpenTaskRead] = Field(default_factory=list)
    spotlight_documents: list[IntelligenceSpotlightDocumentRead] = Field(
        default_factory=list
    )


def _string_meta(
    meta: dict[str, Any], validation_meta: dict[str, Any], *keys: str
) -> str | None:
    for key in keys:
        value = validation_meta.get(key)
        if isinstance(value, str):
            return value
        value = meta.get(key)
        if isinstance(value, str):
            return value
    return None


def _float_meta(
    meta: dict[str, Any], validation_meta: dict[str, Any], key: str
) -> float | None:
    value = validation_meta.get(key, meta.get(key))
    return value if isinstance(value, float | int) else None
