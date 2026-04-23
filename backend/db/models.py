from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
    relationship,
)

from backend.core.config import settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return cls.__name__.lower()


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="role", lazy="selectin")


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint(
            "auth_provider",
            "external_subject",
            name="uq_users_auth_provider_external_subject",
        ),
    )

    auth_provider: Mapped[str] = mapped_column(
        String(50), nullable=False, default="local", index=True
    )
    external_subject: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    username: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(
        String(320), unique=True, nullable=True, index=True
    )
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nextcloud_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    role: Mapped["Role | None"] = relationship(back_populates="users", lazy="selectin")
    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        back_populates="user", passive_deletes=True, lazy="selectin"
    )
    requested_jobs: Mapped[list["SyncJob"]] = relationship(
        back_populates="requested_by", passive_deletes=True, lazy="selectin"
    )
    owned_connectors: Mapped[list["Connector"]] = relationship(
        back_populates="owner", passive_deletes=True, lazy="selectin"
    )


class Connector(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "connectors"

    connector_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="nextcloud"
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    root_path: Mapped[str] = mapped_column(Text, nullable=False, default="/")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="connector",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    sync_jobs: Mapped[list["SyncJob"]] = relationship(
        back_populates="connector",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    owner: Mapped["User | None"] = relationship(
        back_populates="owned_connectors", lazy="selectin"
    )


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "connector_id", "external_id", name="uq_documents_connector_external"
        ),
        Index("ix_documents_connector_file_path", "connector_id", "file_path"),
        Index("ix_documents_connector_sync_status", "connector_id", "sync_status"),
    )

    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("connectors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sync_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    owner_external_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    allowed_user_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String()), nullable=False, default=list
    )
    allowed_group_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String()), nullable=False, default=list
    )
    public_link_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    acl_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    connector: Mapped["Connector"] = relationship(
        back_populates="documents", lazy="selectin"
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="DocumentChunk.chunk_index",
    )
    insights: Mapped[list["DocumentInsight"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="DocumentInsight.created_at.desc()",
    )
    workflow_tasks: Mapped[list["WorkflowTask"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="WorkflowTask.created_at.desc()",
    )


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "chunk_index", name="uq_document_chunks_doc_chunk_index"
        ),
        Index("ix_document_chunks_document_page", "document_id", "page_number"),
        Index(
            "ix_document_chunks_embedding_ann",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"lists": 100},
            postgresql_where=text("embedding IS NOT NULL"),
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.EMBEDDING_DIM), nullable=True
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="chunks", lazy="joined")


class SyncJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (UniqueConstraint("job_key", name="uq_sync_jobs_job_key"),)

    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("connectors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    job_key: Mapped[str] = mapped_column(String(255), nullable=False)
    worker_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, default="sync")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_completed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    connector: Mapped["Connector"] = relationship(
        back_populates="sync_jobs", lazy="selectin"
    )
    requested_by: Mapped["User | None"] = relationship(
        back_populates="requested_jobs", lazy="selectin"
    )


class ChatSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chat_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New chat")
    memory_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    user: Mapped["User"] = relationship(back_populates="chat_sessions", lazy="selectin")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="ChatMessage.created_at",
    )

    @property
    def subject(self) -> str:
        if self.messages:
            latest_content = self.messages[-1].content if self.messages[-1].content else ""
            normalized_content = " ".join(latest_content.split())
            if normalized_content:
                return normalized_content
        return self.title

    @property
    def active_context_document_ids(self) -> list[str]:
        for message in reversed(self.messages):
            if message.role != "assistant" or not message.citations_json:
                continue

            document_ids: list[str] = []
            seen_ids: set[str] = set()
            for citation in message.citations_json:
                if not isinstance(citation, dict):
                    continue
                raw_document_id = citation.get("document_id")
                if not raw_document_id:
                    continue
                document_id = str(raw_document_id)
                if document_id in seen_ids:
                    continue
                seen_ids.add(document_id)
                document_ids.append(document_id)

            if document_ids:
                return document_ids

        return []

    @property
    def active_context_documents(self) -> list[dict[str, str]]:
        for message in reversed(self.messages):
            if message.role != "assistant" or not message.citations_json:
                continue

            documents: list[dict[str, str]] = []
            seen_ids: set[str] = set()
            for citation in message.citations_json:
                if not isinstance(citation, dict):
                    continue
                raw_document_id = citation.get("document_id")
                raw_file_name = citation.get("file_name")
                raw_file_path = citation.get("file_path")
                if not raw_document_id or not raw_file_name or not raw_file_path:
                    continue
                document_id = str(raw_document_id)
                if document_id in seen_ids:
                    continue
                seen_ids.add(document_id)
                documents.append(
                    {
                        "document_id": document_id,
                        "file_name": str(raw_file_name),
                        "file_path": str(raw_file_path),
                    }
                )

            if documents:
                return documents

        return []


class ChatMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations_json: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generation_metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    session: Mapped["ChatSession"] = relationship(
        back_populates="messages", lazy="selectin"
    )


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    user: Mapped["User | None"] = relationship(
        back_populates="audit_logs", lazy="selectin"
    )


class DocumentInsight(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_insights"
    __table_args__ = (
        Index("ix_document_insights_document_type", "document_id", "insight_type"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    insight_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    owner_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="insights", lazy="selectin")
    workflow_tasks: Mapped[list["WorkflowTask"]] = relationship(
        back_populates="insight",
        passive_deletes=True,
        lazy="selectin",
    )


class WorkflowTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_tasks"
    __table_args__ = (
        Index("ix_workflow_tasks_queue_status", "queue_name", "status"),
    )

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    insight_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_insights.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    queue_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")
    priority: Mapped[str] = mapped_column(String(50), nullable=False, default="normal")
    owner_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hook_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hook_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    hook_last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    document: Mapped["Document | None"] = relationship(
        back_populates="workflow_tasks", lazy="selectin"
    )
    insight: Mapped["DocumentInsight | None"] = relationship(
        back_populates="workflow_tasks", lazy="selectin"
    )


class KnowledgeNode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_nodes"
    __table_args__ = (
        UniqueConstraint(
            "node_type", "external_key", name="uq_knowledge_nodes_type_external_key"
        ),
        UniqueConstraint(
            "document_id", name="uq_knowledge_nodes_document_id"
        ),
    )

    node_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    external_key: Mapped[str] = mapped_column(String(255), nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    document: Mapped["Document | None"] = relationship(lazy="selectin")
    outgoing_edges: Mapped[list["KnowledgeEdge"]] = relationship(
        back_populates="source_node",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        foreign_keys="KnowledgeEdge.source_node_id",
    )
    incoming_edges: Mapped[list["KnowledgeEdge"]] = relationship(
        back_populates="target_node",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        foreign_keys="KnowledgeEdge.target_node_id",
    )


class KnowledgeEdge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_edges"
    __table_args__ = (
        UniqueConstraint(
            "source_node_id",
            "target_node_id",
            "relation_type",
            "document_id",
            name="uq_knowledge_edges_relation",
        ),
    )

    source_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    source_node: Mapped["KnowledgeNode"] = relationship(
        back_populates="outgoing_edges",
        lazy="selectin",
        foreign_keys=[source_node_id],
    )
    target_node: Mapped["KnowledgeNode"] = relationship(
        back_populates="incoming_edges",
        lazy="selectin",
        foreign_keys=[target_node_id],
    )
    document: Mapped["Document | None"] = relationship(lazy="selectin")
