"""ensure vector extension

Revision ID: a1b2c3d4e5f6
Revises: 4b7f9d2fd6d1
Create Date: 2026-09-21 17:20:00.000000

Bootstrap compatibility: databases that already applied 00c7539a7dcd before
CREATE EXTENSION was added still get an idempotent extension ensure. Fresh
databases create the extension in 00c7539a7dcd and this migration is a no-op.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "4b7f9d2fd6d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Do not drop the extension: other objects may still depend on it.
    pass
