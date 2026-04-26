"""add document extracted fields

Revision ID: 7f3a2d9c4e81
Revises: 2b7c4f9c1a6d
Create Date: 2026-04-25 22:15:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "7f3a2d9c4e81"
down_revision = "2b7c4f9c1a6d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("extracted_fields_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "extracted_fields_json")
