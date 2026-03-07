from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.models import Document, DocumentChunk
from backend.db.repo.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Document)

    async def get_by_connector_and_external_id(
            self,
            connector_id: UUID,
            external_id: str,
    ) -> Document | None:
        stmt = select(Document).where(
            Document.connector_id == connector_id,
            Document.external_id == external_id,
            )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_chunks(self, document_id: UUID | str) -> Document | None:
        stmt = (
            select(Document)
            .options(selectinload(Document.chunks))
            .where(Document.id == document_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_connector(
            self,
            connector_id: UUID | str,
            *,
            offset: int = 0,
            limit: int = 100,
            include_deleted: bool = False,
    ) -> list[Document]:
        stmt = (
            select(Document)
            .where(Document.connector_id == connector_id)
            .order_by(Document.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if not include_deleted:
            stmt = stmt.where(Document.is_deleted.is_(False))

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def search(
            self,
            *,
            query: str | None = None,
            connector_id: UUID | None = None,
            mime_type: str | None = None,
            parse_status: str | None = None,
            include_deleted: bool = False,
            offset: int = 0,
            limit: int = 50,
    ) -> list[Document]:
        stmt: Select[tuple[Document]] = select(Document)

        filters = []
        if connector_id:
            filters.append(Document.connector_id == connector_id)
        if mime_type:
            filters.append(Document.mime_type == mime_type)
        if parse_status:
            filters.append(Document.parse_status == parse_status)
        if not include_deleted:
            filters.append(Document.is_deleted.is_(False))
        if query:
            like = f"%{query}%"
            filters.append(
                or_(
                    Document.file_name.ilike(like),
                    Document.file_path.ilike(like),
                )
            )

        if filters:
            stmt = stmt.where(and_(*filters))

        stmt = stmt.order_by(Document.updated_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_deleted_missing_from_external_ids(
            self,
            *,
            connector_id: UUID,
            external_ids: Sequence[str],
    ) -> int:
        stmt = (
            update(Document)
            .where(
                Document.connector_id == connector_id,
                Document.external_id.not_in(list(external_ids)),
                Document.is_deleted.is_(False),
                )
            .values(is_deleted=True)
        )
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)

    async def count_chunks(self, document_id: UUID | str) -> int:
        stmt = select(func.count()).select_from(DocumentChunk).where(
            DocumentChunk.document_id == document_id
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())


class DocumentChunkRepository(BaseRepository[DocumentChunk]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DocumentChunk)

    async def list_by_document(self, document_id: UUID | str) -> list[DocumentChunk]:
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def semantic_search(
            self,
            *,
            embedding: list[float],
            limit: int = 8,
            document_ids: Sequence[UUID] | None = None,
    ) -> list[tuple[DocumentChunk, float]]:
        """
        Returns (chunk, distance). Lower distance is better for cosine_distance.
        """
        from sqlalchemy.orm import selectinload

        distance = DocumentChunk.embedding.cosine_distance(embedding).label("distance")
        stmt = (
            select(DocumentChunk, distance)
            .options(selectinload(DocumentChunk.document))
            .where(DocumentChunk.embedding.is_not(None))
        )

        if document_ids:
            stmt = stmt.where(DocumentChunk.document_id.in_(list(document_ids)))

        stmt = stmt.order_by(distance.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return [(row[0], float(row[1])) for row in result.all()]