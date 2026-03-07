from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, selectinload

from backend.core.security import AuthContext
from backend.db.models import Document, DocumentChunk
from backend.db.repo.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Document)

    async def get_by_connector_and_external_id(self, connector_id: UUID, external_id: str) -> Document | None:
        result = await self.session.execute(
            select(Document).where(Document.connector_id == connector_id, Document.external_id == external_id)
        )
        return result.scalar_one_or_none()

    async def get_with_chunks(self, document_id: UUID | str) -> Document | None:
        result = await self.session.execute(
            select(Document).options(selectinload(Document.chunks)).where(Document.id == document_id)
        )
        return result.scalar_one_or_none()

    async def get_visible_to_auth(self, document_id: UUID | str, auth: AuthContext) -> Document | None:
        stmt = select(Document).where(Document.id == document_id, self.visibility_clause(auth))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
        self,
        *,
        auth: AuthContext | None = None,
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
            filters.append(or_(Document.file_name.ilike(like), Document.file_path.ilike(like)))
        if auth is not None:
            filters.append(self.visibility_clause(auth))
        if filters:
            stmt = stmt.where(and_(*filters))
        result = await self.session.execute(stmt.order_by(Document.updated_at.desc()).offset(offset).limit(limit))
        return list(result.scalars().all())

    async def mark_deleted_missing_from_external_ids(self, *, connector_id: UUID, external_ids: Sequence[str]) -> int:
        stmt = (
            update(Document)
            .where(Document.connector_id == connector_id, Document.external_id.not_in(list(external_ids)), Document.is_deleted.is_(False))
            .values(is_deleted=True, sync_status="deleted")
        )
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)

    async def count_chunks(self, document_id: UUID | str) -> int:
        result = await self.session.execute(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == document_id))
        return int(result.scalar_one())

    @staticmethod
    def visibility_clause(auth: AuthContext):
        if auth.is_superuser:
            return Document.is_deleted.is_(False)
        visibility = [Document.public_link_enabled.is_(True)]
        if auth.external_subject:
            visibility.append(Document.owner_external_id == auth.external_subject)
            visibility.append(Document.allowed_user_ids.overlap([auth.external_subject]))
        if auth.groups:
            visibility.append(Document.allowed_group_ids.overlap(auth.groups))
        return and_(Document.is_deleted.is_(False), or_(*visibility))


class DocumentChunkRepository(BaseRepository[DocumentChunk]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DocumentChunk)

    async def replace_for_document(self, document_id: UUID | str, chunks: Sequence[DocumentChunk]) -> None:
        await self.session.execute(update(Document).where(Document.id == document_id).values(parse_status="indexing"))
        existing = await self.list_by_document(document_id)
        for chunk in existing:
            await self.session.delete(chunk)
        for chunk in chunks:
            self.session.add(chunk)
        await self.session.flush()

    async def list_by_document(self, document_id: UUID | str) -> list[DocumentChunk]:
        result = await self.session.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id).order_by(DocumentChunk.chunk_index.asc())
        )
        return list(result.scalars().all())

    async def semantic_search(
        self,
        *,
        embedding: list[float],
        auth: AuthContext,
        limit: int = 8,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[tuple[DocumentChunk, float]]:
        distance = DocumentChunk.embedding.cosine_distance(embedding).label("distance")
        stmt = (
            select(DocumentChunk, distance)
            .join(DocumentChunk.document)
            .options(contains_eager(DocumentChunk.document))
            .where(DocumentChunk.embedding.is_not(None), DocumentRepository.visibility_clause(auth))
            .order_by(distance.asc())
            .limit(limit)
        )
        if document_ids:
            stmt = stmt.where(DocumentChunk.document_id.in_(list(document_ids)))
        result = await self.session.execute(stmt)
        return [(row[0], float(row[1])) for row in result.all()]
