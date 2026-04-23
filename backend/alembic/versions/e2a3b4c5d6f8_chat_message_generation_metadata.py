"""chat message generation metadata

Revision ID: e2a3b4c5d6f8
Revises: c1f4d7a8b932
Create Date: 2026-04-22 20:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e2a3b4c5d6f8"
down_revision: Union[str, Sequence[str], None] = "c1f4d7a8b932"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column(
            "generation_metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "generation_metadata_json")
