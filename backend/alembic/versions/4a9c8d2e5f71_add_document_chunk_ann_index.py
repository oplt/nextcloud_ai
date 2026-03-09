"""add document chunk ann index

Revision ID: 4a9c8d2e5f71
Revises: ff16b1e1c386
Create Date: 2026-03-09 12:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4a9c8d2e5f71"
down_revision: Union[str, Sequence[str], None] = "ff16b1e1c386"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_document_chunks_embedding_ann"
TABLE_NAME = "document_chunks"


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                f"""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME}
                ON {TABLE_NAME}
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
                WHERE embedding IS NOT NULL
                """
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
