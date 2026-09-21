"""Lexical FTS indexes for ts_rank_cd retrieval.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-21 18:10:00.000000

Adds pg_trgm plus GIN indexes used by keyword search. Queries use
``to_tsvector('simple', ...)``; this index covers chunk content so the
``@@`` filter can use it. Filename trigram supports identifier ILIKE.

Rollback: downgrade drops the indexes and extension only if nothing else
depends on pg_trgm. No row rewrite.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_content_fts
        ON document_chunks
        USING gin (to_tsvector('simple', coalesce(content, '')))
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_documents_file_name_trgm
        ON documents
        USING gin (file_name gin_trgm_ops)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_file_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_content_fts")
