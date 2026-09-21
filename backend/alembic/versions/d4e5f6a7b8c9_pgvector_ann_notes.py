"""Pin pgvector ANN behavior and document IVFFlat vs exact/HNSW tradeoffs.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-21 18:40:00.000000

Does not rebuild the existing IVFFlat index (lists=100). Runtime sets
``ivfflat.probes`` via ``PGVECTOR_IVFFLAT_PROBES``. For small authorized
scopes the app prefers exact distance ordering. Evaluate HNSW after a
representative load; do not claim a speedup without benchmarks.

Rollback: no-op (comment-only migration).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure pgvector is present (idempotent). Index rebuilds remain operator-led.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        COMMENT ON INDEX ix_document_chunks_embedding_ann IS
        'IVFFlat cosine ANN (lists=100). Tune probes at query time; rebuild/train after load; consider HNSW when corpus grows.'
        """
    )


def downgrade() -> None:
    op.execute("COMMENT ON INDEX ix_document_chunks_embedding_ann IS NULL")
