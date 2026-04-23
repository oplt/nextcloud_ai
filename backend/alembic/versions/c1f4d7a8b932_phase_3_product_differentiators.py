"""phase 3 product differentiators

Revision ID: c1f4d7a8b932
Revises: 91d8e7b6ce4a
Create Date: 2026-04-22 15:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c1f4d7a8b932"
down_revision: Union[str, Sequence[str], None] = "91d8e7b6ce4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_insights",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("insight_type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("owner_label", sa.String(length=255), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_insights_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_insights")),
    )
    op.create_index(
        "ix_document_insights_document_type",
        "document_insights",
        ["document_id", "insight_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_insights_document_id"),
        "document_insights",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_insights_insight_type"),
        "document_insights",
        ["insight_type"],
        unique=False,
    )

    op.create_table(
        "workflow_tasks",
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("insight_id", sa.UUID(), nullable=True),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column("queue_name", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("priority", sa.String(length=50), nullable=False),
        sa.Column("owner_label", sa.String(length=255), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hook_status", sa.String(length=50), nullable=True),
        sa.Column("hook_response", sa.Text(), nullable=True),
        sa.Column("hook_last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_workflow_tasks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["insight_id"],
            ["document_insights.id"],
            name=op.f("fk_workflow_tasks_insight_id_document_insights"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_tasks")),
    )
    op.create_index(
        "ix_workflow_tasks_queue_status",
        "workflow_tasks",
        ["queue_name", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_tasks_document_id"),
        "workflow_tasks",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_tasks_insight_id"),
        "workflow_tasks",
        ["insight_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_tasks_queue_name"),
        "workflow_tasks",
        ["queue_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_tasks_status"),
        "workflow_tasks",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_tasks_task_type"),
        "workflow_tasks",
        ["task_type"],
        unique=False,
    )

    op.create_table(
        "knowledge_nodes",
        sa.Column("node_type", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("external_key", sa.String(length=255), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_knowledge_nodes_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_nodes")),
        sa.UniqueConstraint(
            "document_id",
            name="uq_knowledge_nodes_document_id",
        ),
        sa.UniqueConstraint(
            "node_type",
            "external_key",
            name="uq_knowledge_nodes_type_external_key",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_nodes_document_id"),
        "knowledge_nodes",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_nodes_label"),
        "knowledge_nodes",
        ["label"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_nodes_node_type"),
        "knowledge_nodes",
        ["node_type"],
        unique=False,
    )

    op.create_table(
        "knowledge_edges",
        sa.Column("source_node_id", sa.UUID(), nullable=False),
        sa.Column("target_node_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("relation_type", sa.String(length=100), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_knowledge_edges_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_node_id"],
            ["knowledge_nodes.id"],
            name=op.f("fk_knowledge_edges_source_node_id_knowledge_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_node_id"],
            ["knowledge_nodes.id"],
            name=op.f("fk_knowledge_edges_target_node_id_knowledge_nodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_edges")),
        sa.UniqueConstraint(
            "source_node_id",
            "target_node_id",
            "relation_type",
            "document_id",
            name="uq_knowledge_edges_relation",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_edges_document_id"),
        "knowledge_edges",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_edges_relation_type"),
        "knowledge_edges",
        ["relation_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_edges_source_node_id"),
        "knowledge_edges",
        ["source_node_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_edges_target_node_id"),
        "knowledge_edges",
        ["target_node_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_edges_target_node_id"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_source_node_id"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_relation_type"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_document_id"), table_name="knowledge_edges")
    op.drop_table("knowledge_edges")

    op.drop_index(op.f("ix_knowledge_nodes_node_type"), table_name="knowledge_nodes")
    op.drop_index(op.f("ix_knowledge_nodes_label"), table_name="knowledge_nodes")
    op.drop_index(op.f("ix_knowledge_nodes_document_id"), table_name="knowledge_nodes")
    op.drop_table("knowledge_nodes")

    op.drop_index(op.f("ix_workflow_tasks_task_type"), table_name="workflow_tasks")
    op.drop_index(op.f("ix_workflow_tasks_status"), table_name="workflow_tasks")
    op.drop_index(op.f("ix_workflow_tasks_queue_name"), table_name="workflow_tasks")
    op.drop_index(op.f("ix_workflow_tasks_insight_id"), table_name="workflow_tasks")
    op.drop_index(op.f("ix_workflow_tasks_document_id"), table_name="workflow_tasks")
    op.drop_index("ix_workflow_tasks_queue_status", table_name="workflow_tasks")
    op.drop_table("workflow_tasks")

    op.drop_index(op.f("ix_document_insights_insight_type"), table_name="document_insights")
    op.drop_index(op.f("ix_document_insights_document_id"), table_name="document_insights")
    op.drop_index("ix_document_insights_document_type", table_name="document_insights")
    op.drop_table("document_insights")
