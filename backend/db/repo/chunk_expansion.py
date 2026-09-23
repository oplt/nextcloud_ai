"""Batched authorized chunk reads for chat evidence expansion."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, defer

from ...core.security import AuthContext
from ..models import Document, DocumentChunk
from .document import DocumentRepository


class AuthorizedChunkExpansionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_grouped(
        self,
        *,
        document_ids: Sequence[UUID | str],
        auth: AuthContext,
        document_ids_scope: Sequence[UUID | str] | None = None,
        per_document_limit: int = 128,
    ) -> dict[str, list[DocumentChunk]]:
        """Fetch a bounded number of chunks per visible document in one query."""
        ids = list(dict.fromkeys(str(item) for item in document_ids))
        if document_ids_scope is not None:
            scope = {str(item) for item in document_ids_scope}
            ids = [item for item in ids if item in scope]
        grouped = {item: [] for item in ids}
        if not ids:
            return grouped

        row_number = func.row_number().over(
            partition_by=DocumentChunk.document_id,
            order_by=DocumentChunk.chunk_index.asc(),
        )
        ranked = (
            select(
                DocumentChunk.id.label("chunk_id"),
                row_number.label("document_row_number"),
            )
            .where(DocumentChunk.document_id.in_(ids))
            .subquery()
        )
        stmt = (
            select(DocumentChunk)
            .join(ranked, ranked.c.chunk_id == DocumentChunk.id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .options(
                contains_eager(DocumentChunk.document),
                defer(DocumentChunk.embedding),
            )
            .where(
                ranked.c.document_row_number <= max(1, per_document_limit),
                DocumentRepository.visibility_clause(auth),
            )
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
        )
        result = await self.session.execute(stmt)
        for chunk in result.scalars().all():
            grouped.setdefault(str(chunk.document_id), []).append(chunk)
        return grouped
