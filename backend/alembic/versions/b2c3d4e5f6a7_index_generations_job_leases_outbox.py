"""Phase 2: index generations, job leases, work outbox.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-21 17:40:00.000000

Adds:
- documents.index_generation / published_generation for optimistic publish
- sync_jobs.lease_owner / lease_expires_at / last_heartbeat_at
- work_outbox for post-commit task dispatch (intelligence, etc.)

Rollback: downgrade drops new columns/table. Pending outbox rows are lost on
downgrade; re-run intelligence extraction for affected documents if needed.
No bulk index rebuild is performed by this migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "index_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "published_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.add_column(
        "sync_jobs",
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "sync_jobs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sync_jobs",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_sync_jobs_status_lease_expires_at",
        "sync_jobs",
        ["status", "lease_expires_at"],
        unique=False,
    )

    op.create_table(
        "work_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("topic", sa.String(length=100), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_work_outbox_idempotency_key"),
    )
    op.create_index(
        "ix_work_outbox_status_available_at",
        "work_outbox",
        ["status", "available_at"],
        unique=False,
    )
    op.create_index("ix_work_outbox_topic", "work_outbox", ["topic"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_work_outbox_topic", table_name="work_outbox")
    op.drop_index("ix_work_outbox_status_available_at", table_name="work_outbox")
    op.drop_table("work_outbox")

    op.drop_index("ix_sync_jobs_status_lease_expires_at", table_name="sync_jobs")
    op.drop_column("sync_jobs", "last_heartbeat_at")
    op.drop_column("sync_jobs", "lease_expires_at")
    op.drop_column("sync_jobs", "lease_owner")

    op.drop_column("documents", "published_generation")
    op.drop_column("documents", "index_generation")
