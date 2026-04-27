"""add indexes and workflow constraints

Revision ID: 4b7f9d2fd6d1
Revises: 00c7539a7dcd
Create Date: 2026-04-27 17:18:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4b7f9d2fd6d1"
down_revision: Union[str, Sequence[str], None] = "00c7539a7dcd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_sync_jobs_status_created_at",
        "sync_jobs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_sync_jobs_connector_status_created_at",
        "sync_jobs",
        ["connector_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_documents_connector_updated_at",
        "documents",
        ["connector_id", "updated_at"],
        unique=False,
    )
    op.create_index("ix_documents_modified_at", "documents", ["modified_at"], unique=False)
    op.create_index("ix_documents_updated_at", "documents", ["updated_at"], unique=False)
    op.create_index(
        "ix_workflow_tasks_status_due_at",
        "workflow_tasks",
        ["status", "due_at"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_tasks_metadata_json",
        "workflow_tasks",
        ["metadata_json"],
        unique=False,
        postgresql_using="gin",
    )

    op.create_check_constraint(
        "ck_documents_document_type_confidence_range",
        "documents",
        sa.text("document_type_confidence >= 0.0 AND document_type_confidence <= 1.0"),
    )
    op.create_check_constraint(
        "ck_documents_business_domain_confidence_range",
        "documents",
        sa.text(
            "business_domain_confidence >= 0.0 AND business_domain_confidence <= 1.0"
        ),
    )
    op.create_check_constraint(
        "ck_sync_jobs_status_enum",
        "sync_jobs",
        sa.text(
            "status IN ('queued','pending','running','processing','retrying','succeeded','completed','done','failed','error','dead_lettered')"
        ),
    )
    op.create_check_constraint(
        "ck_workflow_tasks_status_enum",
        "workflow_tasks",
        sa.text(
            "status IN ('queued','in_progress','blocked','needs_review','suggested','approved','dismissed','done','failed')"
        ),
    )
    op.create_check_constraint(
        "ck_workflow_tasks_priority_enum",
        "workflow_tasks",
        sa.text("priority IN ('low','normal','high','urgent','critical')"),
    )


def downgrade() -> None:
    op.drop_constraint("ck_workflow_tasks_priority_enum", "workflow_tasks", type_="check")
    op.drop_constraint("ck_workflow_tasks_status_enum", "workflow_tasks", type_="check")
    op.drop_constraint("ck_sync_jobs_status_enum", "sync_jobs", type_="check")
    op.drop_constraint(
        "ck_documents_business_domain_confidence_range",
        "documents",
        type_="check",
    )
    op.drop_constraint(
        "ck_documents_document_type_confidence_range",
        "documents",
        type_="check",
    )

    op.drop_index("ix_workflow_tasks_metadata_json", table_name="workflow_tasks")
    op.drop_index("ix_workflow_tasks_status_due_at", table_name="workflow_tasks")
    op.drop_index("ix_documents_updated_at", table_name="documents")
    op.drop_index("ix_documents_modified_at", table_name="documents")
    op.drop_index("ix_documents_connector_updated_at", table_name="documents")
    op.drop_index("ix_sync_jobs_connector_status_created_at", table_name="sync_jobs")
    op.drop_index("ix_sync_jobs_status_created_at", table_name="sync_jobs")
