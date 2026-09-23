"""Align the chunk GIN index with the weighted lexical query expression.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-22 12:00:00.000000

The earlier content-only index cannot serve the weighted content/heading
expression used by retrieval. This migration replaces it without rewriting
document rows. Creating the index may briefly lock writes on large corpora;
schedule the migration accordingly.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_content_fts")
    op.execute(
        """
        CREATE INDEX ix_document_chunks_content_fts
        ON document_chunks
        USING gin ((
            setweight(
                to_tsvector('simple'::regconfig, coalesce(content, '')),
                'A'
            ) ||
            setweight(
                to_tsvector(
                    'simple'::regconfig,
                    coalesce(section_title, '') || ' ' || coalesce(heading_path, '')
                ),
                'B'
            )
        ))
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_content_fts")
    op.execute(
        """
        CREATE INDEX ix_document_chunks_content_fts
        ON document_chunks
        USING gin (to_tsvector('simple', coalesce(content, '')))
        """
    )
