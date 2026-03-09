from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from backend.db.models import DocumentChunk


def test_document_chunk_embedding_ann_index_uses_cosine_ivfflat() -> None:
    index = next(
        idx
        for idx in DocumentChunk.__table__.indexes
        if idx.name == "ix_document_chunks_embedding_ann"
    )

    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))

    assert "USING ivfflat" in ddl
    assert "vector_cosine_ops" in ddl
    assert "lists = 100" in ddl
    assert "WHERE embedding IS NOT NULL" in ddl
