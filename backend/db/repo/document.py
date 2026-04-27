from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, Text, and_, cast, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, selectinload

from ...core.security import AuthContext, auth_user_identifiers
from ..models import Document, DocumentChunk
from .base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Document)

    async def get_by_connector_and_external_id(
            self, connector_id: UUID, external_id: str
    ) -> Document | None:
        result = await self.session.execute(
            select(Document).where(
                Document.connector_id == connector_id,
                Document.external_id == external_id,
                )
        )
        return result.scalar_one_or_none()

    async def get_by_connector_and_file_path(
            self, connector_id: UUID | str, file_path: str
    ) -> Document | None:
        result = await self.session.execute(
            select(Document).where(
                Document.connector_id == connector_id,
                Document.file_path == file_path,
            )
        )
        return result.scalar_one_or_none()

    async def get_with_chunks(self, document_id: UUID | str) -> Document | None:
        result = await self.session.execute(
            select(Document)
            .options(selectinload(Document.chunks))
            .where(Document.id == document_id)
        )
        return result.scalar_one_or_none()

    async def get_with_chunks_visible_to_auth(
            self, document_id: UUID | str, auth: AuthContext
    ) -> Document | None:
        result = await self.session.execute(
            select(Document)
            .options(selectinload(Document.chunks))
            .where(Document.id == document_id, self.visibility_clause(auth))
        )
        return result.scalar_one_or_none()

    async def get_visible_to_auth(
            self, document_id: UUID | str, auth: AuthContext
    ) -> Document | None:
        stmt = select(Document).where(
            Document.id == document_id, self.visibility_clause(auth)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
            self,
            *,
            auth: AuthContext | None = None,
            query: str | None = None,
            connector_id: UUID | None = None,
            connector_ids: Sequence[UUID | str] | None = None,
            mime_type: str | None = None,
            mime_types: Sequence[str] | None = None,
            path_prefixes: Sequence[str] | None = None,
            modified_after: datetime | None = None,
            modified_before: datetime | None = None,
            parse_status: str | None = None,
            document_type: str | None = None,
            business_domain: str | None = None,
            source_type: str | None = None,
            needs_review: bool | None = None,
            low_confidence: bool | None = None,
            include_deleted: bool = False,
            include_intelligence: bool = False,
            include_chunks: bool = False,
            offset: int = 0,
            limit: int = 50,
    ) -> list[Document]:
        stmt: Select[tuple[Document]] = select(Document)
        if include_chunks:
            stmt = stmt.options(selectinload(Document.chunks))
        if include_intelligence:
            stmt = stmt.options(
                selectinload(Document.insights),
                selectinload(Document.workflow_tasks),
            )
        filters = self._build_search_filters(
            auth=auth,
            query=query,
            connector_id=connector_id,
            connector_ids=connector_ids,
            mime_type=mime_type,
            mime_types=mime_types,
            path_prefixes=path_prefixes,
            modified_after=modified_after,
            modified_before=modified_before,
            parse_status=parse_status,
            document_type=document_type,
            business_domain=business_domain,
            source_type=source_type,
            needs_review=needs_review,
            low_confidence=low_confidence,
            include_deleted=include_deleted,
        )
        if filters:
            stmt = stmt.where(and_(*filters))
        result = await self.session.execute(
            stmt.order_by(Document.updated_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

    async def count_search(
        self,
        *,
        auth: AuthContext | None = None,
        query: str | None = None,
        connector_id: UUID | None = None,
        connector_ids: Sequence[UUID | str] | None = None,
        mime_type: str | None = None,
        mime_types: Sequence[str] | None = None,
        path_prefixes: Sequence[str] | None = None,
        modified_after: datetime | None = None,
        modified_before: datetime | None = None,
        parse_status: str | None = None,
        document_type: str | None = None,
        business_domain: str | None = None,
        source_type: str | None = None,
        needs_review: bool | None = None,
        low_confidence: bool | None = None,
        include_deleted: bool = False,
    ) -> int:
        filters = self._build_search_filters(
            auth=auth,
            query=query,
            connector_id=connector_id,
            connector_ids=connector_ids,
            mime_type=mime_type,
            mime_types=mime_types,
            path_prefixes=path_prefixes,
            modified_after=modified_after,
            modified_before=modified_before,
            parse_status=parse_status,
            document_type=document_type,
            business_domain=business_domain,
            source_type=source_type,
            needs_review=needs_review,
            low_confidence=low_confidence,
            include_deleted=include_deleted,
        )
        stmt = select(func.count()).select_from(Document)
        if filters:
            stmt = stmt.where(and_(*filters))
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def count_chunks_by_document_ids(
        self, document_ids: Sequence[UUID | str]
    ) -> dict[str, int]:
        if not document_ids:
            return {}
        result = await self.session.execute(
            select(DocumentChunk.document_id, func.count(DocumentChunk.id))
            .where(DocumentChunk.document_id.in_(list(document_ids)))
            .group_by(DocumentChunk.document_id)
        )
        return {str(document_id): int(count) for document_id, count in result.all()}

    async def search_documents(
            self,
            *,
            auth: AuthContext,
            terms: Sequence[str],
            connector_ids: Sequence[UUID | str] | None = None,
            path_prefixes: Sequence[str] | None = None,
            modified_after: datetime | None = None,
            modified_before: datetime | None = None,
            document_types: Sequence[str] | None = None,
            business_domains: Sequence[str] | None = None,
            source_types: Sequence[str] | None = None,
            limit: int = 20,
    ) -> list[Document]:
        normalized_terms = [term.strip() for term in terms if term.strip()]
        if not normalized_terms:
            return []

        clauses = []
        for term in normalized_terms:
            pattern = f"%{term}%"
            clauses.extend(
                [
                    Document.file_name.ilike(pattern),
                    Document.file_path.ilike(pattern),
                    Document.document_type.ilike(pattern),
                    Document.business_domain.ilike(pattern),
                    cast(Document.metadata_json, Text).ilike(pattern),
                    cast(Document.extracted_fields_json, Text).ilike(pattern),
                    DocumentChunk.content.ilike(pattern),
                ]
            )

        stmt = (
            select(Document)
            .outerjoin(Document.chunks)
            .options(selectinload(Document.chunks))
            .where(DocumentRepository.visibility_clause(auth), or_(*clauses))
            .order_by(Document.modified_at.desc().nullslast(), Document.updated_at.desc())
            .limit(limit)
        )
        stmt = self._apply_document_filters(
            stmt,
            connector_ids=connector_ids,
            path_prefixes=path_prefixes,
            modified_after=modified_after,
            modified_before=modified_before,
            document_types=document_types,
            business_domains=business_domains,
            source_types=source_types,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def mark_deleted_missing_from_external_ids(
            self, *, connector_id: UUID, external_ids: Sequence[str]
    ) -> int:
        stmt = (
            update(Document)
            .where(
                Document.connector_id == connector_id,
                Document.external_id.not_in(list(external_ids)),
                Document.is_deleted.is_(False),
                )
            .values(is_deleted=True, sync_status="deleted")
        )
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)

    async def count_chunks(self, document_id: UUID | str) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        )
        return int(result.scalar_one())

    async def has_unusable_chunks(self, document_id: UUID | str) -> bool:
        result = await self.session.execute(
            select(
                func.count(DocumentChunk.id),
                func.count().filter(
                    or_(
                        DocumentChunk.embedding_status != "embedded",
                        DocumentChunk.embedding.is_(None),
                    )
                ),
            ).where(DocumentChunk.document_id == document_id)
        )
        chunk_count, unusable_count = result.one()
        return int(chunk_count or 0) == 0 or int(unusable_count or 0) > 0

    async def find_indexed_duplicate(
        self, *, checksum: str, source_type: str, exclude_document_id: UUID | str
    ) -> Document | None:
        result = await self.session.execute(
            select(Document).where(
                Document.checksum == checksum,
                Document.source_type == source_type,
                Document.id != exclude_document_id,
                Document.parse_status == "indexed",
                Document.is_deleted.is_(False),
            )
        )
        return result.scalars().first()

    @staticmethod
    def visibility_clause(auth: AuthContext):
        if auth.is_superuser:
            return Document.is_deleted.is_(False)
        visibility = [Document.public_link_enabled.is_(True)]
        user_identifiers = auth_user_identifiers(auth)
        if user_identifiers:
            visibility.append(Document.owner_external_id.in_(user_identifiers))
            visibility.append(Document.allowed_user_ids.overlap(user_identifiers))
        if auth.groups:
            visibility.append(Document.allowed_group_ids.overlap(auth.groups))
        return and_(Document.is_deleted.is_(False), or_(*visibility))

    @staticmethod
    def _apply_document_filters(
        stmt: Select,
        *,
        connector_ids: Sequence[UUID | str] | None = None,
        path_prefixes: Sequence[str] | None = None,
        modified_after: datetime | None = None,
        modified_before: datetime | None = None,
        document_types: Sequence[str] | None = None,
        business_domains: Sequence[str] | None = None,
        source_types: Sequence[str] | None = None,
    ) -> Select:
        if connector_ids:
            stmt = stmt.where(Document.connector_id.in_(list(connector_ids)))
        if path_prefixes:
            stmt = stmt.where(
                or_(
                    *[
                        Document.file_path.ilike(f"{path_prefix.rstrip('%')}%")
                        for path_prefix in path_prefixes
                        if path_prefix
                    ]
                )
            )
        if modified_after is not None:
            stmt = stmt.where(Document.modified_at >= modified_after)
        if modified_before is not None:
            stmt = stmt.where(Document.modified_at <= modified_before)
        if document_types:
            stmt = stmt.where(Document.document_type.in_(list(document_types)))
        if business_domains:
            stmt = stmt.where(Document.business_domain.in_(list(business_domains)))
        if source_types:
            stmt = stmt.where(Document.source_type.in_(list(source_types)))
        return stmt

    @staticmethod
    def _build_search_filters(
        *,
        auth: AuthContext | None = None,
        query: str | None = None,
        connector_id: UUID | None = None,
        connector_ids: Sequence[UUID | str] | None = None,
        mime_type: str | None = None,
        mime_types: Sequence[str] | None = None,
        path_prefixes: Sequence[str] | None = None,
        modified_after: datetime | None = None,
        modified_before: datetime | None = None,
        parse_status: str | None = None,
        document_type: str | None = None,
        business_domain: str | None = None,
        source_type: str | None = None,
        needs_review: bool | None = None,
        low_confidence: bool | None = None,
        include_deleted: bool = False,
    ) -> list[object]:
        filters: list[object] = []
        if connector_id:
            filters.append(Document.connector_id == connector_id)
        if connector_ids:
            filters.append(Document.connector_id.in_(list(connector_ids)))
        if mime_type:
            filters.append(Document.mime_type == mime_type)
        if mime_types:
            filters.append(Document.mime_type.in_(list(mime_types)))
        if path_prefixes:
            filters.append(
                or_(
                    *[
                        Document.file_path.ilike(f"{path_prefix.rstrip('%')}%")
                        for path_prefix in path_prefixes
                        if path_prefix
                    ]
                )
            )
        if modified_after is not None:
            filters.append(Document.modified_at >= modified_after)
        if modified_before is not None:
            filters.append(Document.modified_at <= modified_before)
        if parse_status:
            filters.append(Document.parse_status == parse_status)
        if document_type:
            filters.append(Document.document_type == document_type)
        if business_domain:
            filters.append(Document.business_domain == business_domain)
        if source_type:
            filters.append(Document.source_type == source_type)
        if needs_review:
            filters.append(
                or_(
                    Document.parse_status.in_(["failed", "needs_ocr", "unsupported_type"]),
                    Document.document_type == "unclassified",
                    Document.business_domain == "unknown",
                    Document.document_type_confidence < 0.6,
                    Document.business_domain_confidence < 0.6,
                )
            )
        if low_confidence:
            filters.append(
                or_(
                    Document.document_type_confidence < 0.6,
                    Document.business_domain_confidence < 0.6,
                )
            )
        if not include_deleted:
            filters.append(Document.is_deleted.is_(False))
        if query:
            like = f"%{query}%"
            filters.append(
                or_(
                    Document.file_name.ilike(like),
                    Document.file_path.ilike(like),
                    Document.document_type.ilike(like),
                    Document.business_domain.ilike(like),
                )
            )
        if auth is not None:
            filters.append(DocumentRepository.visibility_clause(auth))
        return filters


class DocumentChunkRepository(BaseRepository[DocumentChunk]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DocumentChunk)

    async def delete_for_document(
            self, document_id: UUID | str, *, flush: bool = False
    ) -> int:
        result = await self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        if flush:
            await self.session.flush()
        return int(result.rowcount or 0)

    async def replace_for_document(
            self, document_id: UUID | str, chunks: Sequence[DocumentChunk]
    ) -> None:
        await self.session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(parse_status="parsing")
        )
        await self.delete_for_document(document_id)
        self.session.add_all(list(chunks))
        await self.session.flush()

    async def list_by_document(self, document_id: UUID | str) -> list[DocumentChunk]:
        result = await self.session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        return list(result.scalars().all())

    async def semantic_search(
            self,
            *,
            embedding: list[float],
            auth: AuthContext,
            limit: int = 8,
            document_ids: Sequence[UUID] | None = None,
            connector_ids: Sequence[UUID | str] | None = None,
            mime_types: Sequence[str] | None = None,
            path_prefixes: Sequence[str] | None = None,
            modified_after: datetime | None = None,
            modified_before: datetime | None = None,
            document_types: Sequence[str] | None = None,
            business_domains: Sequence[str] | None = None,
            source_types: Sequence[str] | None = None,
            parse_status: str | None = "indexed",
    ) -> list[tuple[DocumentChunk, float]]:
        distance = DocumentChunk.embedding.cosine_distance(embedding).label("distance")
        stmt = (
            select(DocumentChunk, distance)
            .join(DocumentChunk.document)
            .options(contains_eager(DocumentChunk.document))
            .where(
                DocumentChunk.embedding.is_not(None),
                DocumentRepository.visibility_clause(auth),
            )
            .order_by(distance.asc())
            .limit(limit)
        )
        if document_ids:
            stmt = stmt.where(DocumentChunk.document_id.in_(list(document_ids)))
        stmt = self._apply_chunk_document_filters(
            stmt,
            connector_ids=connector_ids,
            mime_types=mime_types,
            path_prefixes=path_prefixes,
            modified_after=modified_after,
            modified_before=modified_before,
            document_types=document_types,
            business_domains=business_domains,
            source_types=source_types,
            parse_status=parse_status,
        )
        result = await self.session.execute(stmt)
        return [(row[0], float(row[1])) for row in result.all()]

    async def keyword_search(
            self,
            *,
            terms: Sequence[str],
            auth: AuthContext,
            limit: int = 16,
            document_ids: Sequence[UUID] | None = None,
            connector_ids: Sequence[UUID | str] | None = None,
            mime_types: Sequence[str] | None = None,
            path_prefixes: Sequence[str] | None = None,
            modified_after: datetime | None = None,
            modified_before: datetime | None = None,
            document_types: Sequence[str] | None = None,
            business_domains: Sequence[str] | None = None,
            source_types: Sequence[str] | None = None,
            parse_status: str | None = "indexed",
    ) -> list[DocumentChunk]:
        normalized_terms = [term.strip() for term in terms if term.strip()]
        if not normalized_terms:
            return []

        like_clauses = []
        for term in normalized_terms:
            pattern = f"%{term}%"
            like_clauses.extend(
                [
                    DocumentChunk.content.ilike(pattern),
                    DocumentChunk.section_title.ilike(pattern),
                    Document.file_name.ilike(pattern),
                    Document.file_path.ilike(pattern),
                    Document.document_type.ilike(pattern),
                    Document.business_domain.ilike(pattern),
                    cast(Document.metadata_json, Text).ilike(pattern),
                    cast(Document.extracted_fields_json, Text).ilike(pattern),
                ]
            )

        stmt = (
            select(DocumentChunk)
            .join(DocumentChunk.document)
            .options(contains_eager(DocumentChunk.document))
            .where(DocumentRepository.visibility_clause(auth), or_(*like_clauses))
            .order_by(DocumentChunk.chunk_index.asc())
            .limit(limit)
        )
        if document_ids:
            stmt = stmt.where(DocumentChunk.document_id.in_(list(document_ids)))
        stmt = self._apply_chunk_document_filters(
            stmt,
            connector_ids=connector_ids,
            mime_types=mime_types,
            path_prefixes=path_prefixes,
            modified_after=modified_after,
            modified_before=modified_before,
            document_types=document_types,
            business_domains=business_domains,
            source_types=source_types,
            parse_status=parse_status,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    @staticmethod
    def _apply_chunk_document_filters(
        stmt: Select,
        *,
        connector_ids: Sequence[UUID | str] | None = None,
        mime_types: Sequence[str] | None = None,
        path_prefixes: Sequence[str] | None = None,
        modified_after: datetime | None = None,
        modified_before: datetime | None = None,
        document_types: Sequence[str] | None = None,
        business_domains: Sequence[str] | None = None,
        source_types: Sequence[str] | None = None,
        parse_status: str | None = "indexed",
    ) -> Select:
        if connector_ids:
            stmt = stmt.where(Document.connector_id.in_(list(connector_ids)))
        if mime_types:
            stmt = stmt.where(Document.mime_type.in_(list(mime_types)))
        if path_prefixes:
            stmt = stmt.where(
                or_(
                    *[
                        Document.file_path.ilike(f"{path_prefix.rstrip('%')}%")
                        for path_prefix in path_prefixes
                        if path_prefix
                    ]
                )
            )
        if modified_after is not None:
            stmt = stmt.where(Document.modified_at >= modified_after)
        if modified_before is not None:
            stmt = stmt.where(Document.modified_at <= modified_before)
        if document_types:
            stmt = stmt.where(Document.document_type.in_(list(document_types)))
        if business_domains:
            stmt = stmt.where(Document.business_domain.in_(list(business_domains)))
        if source_types:
            stmt = stmt.where(Document.source_type.in_(list(source_types)))
        if parse_status:
            stmt = stmt.where(Document.parse_status == parse_status)
        return stmt
