"""chat session memory_json

Revision ID: f3c9a1b2d4e5
Revises: e2a3b4c5d6f8
Create Date: 2026-04-22 22:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f3c9a1b2d4e5"
down_revision: Union[str, Sequence[str], None] = "e2a3b4c5d6f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column(
            "memory_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "memory_json")
