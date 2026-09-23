from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Select,
    and_,
    case,
    delete,
    func,
    literal_column,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, defer, selectinload

from ...core.security import AuthContext, auth_acl_groups, auth_acl_principals
from ...rag.lexical import LEXICAL_REGCONFIG, looks_like_identifier
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

    async def get_by_connector_and_external_id_for_update(
        self, connector_id: UUID, external_id: str
    ) -> Document | None:
        """Lock one source record while its new index generation is prepared."""
        result = await self.session.execute(
            select(Document)
            .where(
                Document.connector_id == connector_id,
                Document.external_id == external_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, document_id: UUID | str) -> Document | None:
        """Lock a document for generation-bound idempotent publication."""
        result = await self.session.execute(
            select(Document).where(Document.id == document_id).with_for_update()
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
            .options(
                selectinload(Document.chunks).defer(DocumentChunk.embedding),
            )
            .where(Document.id == document_id)
        )
        return result.scalar_one_or_none()

    async def get_with_chunks_visible_to_auth(
        self, document_id: UUID | str, auth: AuthContext
    ) -> Document | None:
        result = await self.session.execute(
            select(Document)
            .options(
                selectinload(Document.chunks).defer(DocumentChunk.embedding),
            )
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

    async def count_visible_by_field(
        self,
        *,
        auth: AuthContext,
        field: str,
    ) -> dict[str, int]:
        """Authorized SQL aggregates. ``field`` is document_type or business_domain."""
        column = {
            "document_type": Document.document_type,
            "business_domain": Document.business_domain,
        }.get(field)
        if column is None:
            raise ValueError(f"unsupported aggregate field: {field}")
        stmt = (
            select(column, func.count())
            .where(DocumentRepository.visibility_clause(auth))
            .group_by(column)
        )
        result = await self.session.execute(stmt)
        counts: dict[str, int] = {}
        for value, count in result.all():
            key = str(value or "unknown").strip() or "unknown"
            if key in {"", "unclassified", "unknown"} and field == "document_type":
                if key in {"", "unclassified"}:
                    continue
            if field == "business_domain" and key == "unknown":
                continue
            counts[key] = int(count)
        return counts

    async def list_spotlight_documents(
        self,
        *,
        auth: AuthContext,
        limit: int = 12,
    ) -> list[Document]:
        """Paginated spotlight rows with intelligence collections. Not a global total."""
        return await self.search(
            auth=auth,
            limit=limit,
            include_intelligence=True,
        )

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
        mime_types: Sequence[str] | None = None,
        source_types: Sequence[str] | None = None,
        limit: int = 20,
    ) -> list[tuple[Document, float, str | None]]:
        """Distinct documents ordered by best ``ts_rank_cd``. Limit is per document."""
        normalized_terms = [term.strip() for term in terms if term.strip()]
        if not normalized_terms:
            return []

        chunk_rank = DocumentChunkRepository._best_chunk_rank_subquery(normalized_terms)
        chunk_vector = DocumentChunkRepository._chunk_tsvector()
        excerpt_rank, excerpt_match = DocumentChunkRepository._lexical_rank_and_match(
            chunk_vector, normalized_terms
        )
        matched_excerpt = (
            select(DocumentChunk.content)
            .where(
                DocumentChunk.document_id == Document.id,
                excerpt_match,
            )
            .order_by(excerpt_rank.desc(), DocumentChunk.chunk_index.asc())
            .limit(1)
            .correlate(Document)
            .scalar_subquery()
            .label("matched_excerpt")
        )
        score = func.greatest(
            func.coalesce(chunk_rank.c.lexical_rank, 0.0),
            DocumentChunkRepository._filename_identifier_boost(normalized_terms),
        ).label("lexical_rank")
        stmt = (
            select(Document, score, matched_excerpt)
            .outerjoin(chunk_rank, chunk_rank.c.document_id == Document.id)
            .where(
                DocumentRepository.visibility_clause(auth),
                DocumentChunkRepository._document_lexical_match(
                    normalized_terms, chunk_rank
                ),
            )
            .order_by(score.desc(), Document.modified_at.desc().nullslast())
            .limit(limit)
        )
        stmt = self._apply_document_filters(
            stmt,
            connector_ids=connector_ids,
            mime_types=mime_types,
            path_prefixes=path_prefixes,
            modified_after=modified_after,
            modified_before=modified_before,
            document_types=document_types,
            business_domains=business_domains,
            source_types=source_types,
        )
        result = await self.session.execute(stmt)
        return [
            (row[0], float(row[1] or 0.0), str(row[2]) if row[2] else None)
            for row in result.all()
        ]

    async def count_search_documents(
        self,
        *,
        auth: AuthContext,
        terms: Sequence[str],
        connector_ids: Sequence[UUID | str] | None = None,
        mime_types: Sequence[str] | None = None,
        path_prefixes: Sequence[str] | None = None,
        modified_after: datetime | None = None,
        modified_before: datetime | None = None,
        document_types: Sequence[str] | None = None,
        business_domains: Sequence[str] | None = None,
        source_types: Sequence[str] | None = None,
    ) -> int:
        normalized_terms = [term.strip() for term in terms if term.strip()]
        if not normalized_terms:
            return 0
        chunk_rank = DocumentChunkRepository._best_chunk_rank_subquery(normalized_terms)
        stmt = (
            select(func.count(Document.id))
            .select_from(Document)
            .outerjoin(chunk_rank, chunk_rank.c.document_id == Document.id)
            .where(
                DocumentRepository.visibility_clause(auth),
                DocumentChunkRepository._document_lexical_match(
                    normalized_terms, chunk_rank
                ),
            )
        )
        stmt = self._apply_document_filters(
            stmt,
            connector_ids=connector_ids,
            mime_types=mime_types,
            path_prefixes=path_prefixes,
            modified_after=modified_after,
            modified_before=modified_before,
            document_types=document_types,
            business_domains=business_domains,
            source_types=source_types,
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

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

    async def mark_deleted_missing_imap_uids(
        self,
        *,
        connector_id: UUID,
        present_uids: Sequence[str],
        mailbox: str | None = None,
        uidvalidity: int | None = None,
    ) -> int:
        """Soft-delete email docs whose stored IMAP UID is absent from a complete inventory.

        Documents without ``metadata_json.imap_uid`` are retained (legacy/unknown).
        """
        present = {str(uid) for uid in present_uids if str(uid).strip()}
        stmt = select(Document).where(
            Document.connector_id == connector_id,
            Document.is_deleted.is_(False),
        )
        result = await self.session.execute(stmt)
        deleted = 0
        for document in result.scalars().all():
            meta = document.metadata_json or {}
            source_kind = str(meta.get("source_kind") or "")
            if source_kind not in {"email_message", "email_attachment"}:
                continue
            imap_uid = str(meta.get("imap_uid") or "").strip()
            if not imap_uid:
                continue
            if mailbox is not None:
                stored_mailbox = str(meta.get("imap_mailbox") or "")
                if stored_mailbox and stored_mailbox != mailbox:
                    continue
            if uidvalidity is not None:
                stored_validity = meta.get("imap_uidvalidity")
                if stored_validity is None:
                    # Legacy document with unknown epoch: retain until a
                    # successful fetch stamps a trustworthy UIDVALIDITY.
                    continue
                try:
                    same_epoch = int(stored_validity) == int(uidvalidity)
                except (TypeError, ValueError):
                    same_epoch = False
                if not same_epoch:
                    # Different UIDVALIDITY epoch — do not delete across renumbering.
                    continue
            if imap_uid in present:
                continue
            document.is_deleted = True
            document.sync_status = "deleted"
            deleted += 1
        if deleted:
            await self.session.flush()
        return deleted

    async def mark_deleted_missing_email_attachments(
        self,
        *,
        connector_id: UUID,
        imap_uid: str,
        mailbox: str,
        uidvalidity: int,
        present_external_ids: Sequence[str],
    ) -> int:
        """Delete stale attachment rows after one message was fetched successfully.

        This reconciliation is intentionally message-scoped. A failed or skipped
        body fetch never calls it, so existing attachment indexes are retained.
        """
        present = {str(item) for item in present_external_ids}
        stmt = select(Document).where(
            Document.connector_id == connector_id,
            Document.is_deleted.is_(False),
        )
        result = await self.session.execute(stmt)
        deleted = 0
        for document in result.scalars().all():
            meta = document.metadata_json or {}
            if str(meta.get("source_kind") or "") != "email_attachment":
                continue
            if str(meta.get("imap_uid") or "") != str(imap_uid):
                continue
            if str(meta.get("imap_mailbox") or "") != mailbox:
                continue
            try:
                same_epoch = int(meta.get("imap_uidvalidity")) == int(uidvalidity)
            except (TypeError, ValueError):
                same_epoch = False
            if not same_epoch or str(document.external_id) in present:
                continue
            document.is_deleted = True
            document.sync_status = "deleted"
            deleted += 1
        if deleted:
            await self.session.flush()
        return deleted

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
                Document.parse_status.in_(("indexed", "lexical_ready")),
                Document.is_deleted.is_(False),
            )
        )
        return result.scalars().first()

    @staticmethod
    def visibility_clause(auth: AuthContext):
        """Authorized, non-deleted documents only.

        Public/possession-based Nextcloud links are never treated as universal
        read for authenticated app users.
        """
        if auth.is_superuser:
            return Document.is_deleted.is_(False)
        visibility: list[object] = []
        principals = auth_acl_principals(auth)
        if principals:
            visibility.append(Document.owner_external_id.in_(principals))
            visibility.append(Document.allowed_user_ids.overlap(principals))
        groups = auth_acl_groups(auth)
        if groups:
            visibility.append(Document.allowed_group_ids.overlap(groups))
        if not visibility:
            # Fail closed: no principals → no document visibility.
            return and_(Document.is_deleted.is_(False), Document.id.is_(None))
        return and_(Document.is_deleted.is_(False), or_(*visibility))

    @staticmethod
    def _apply_document_filters(
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
                    Document.parse_status.in_(
                        ["failed", "needs_ocr", "unsupported_type"]
                    ),
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
        self,
        document_id: UUID | str,
        chunks: Sequence[DocumentChunk],
        *,
        touch_parse_status: bool = False,
    ) -> None:
        """Replace chunk rows for a document.

        Status transitions belong to the ingestion pipeline. The historical
        ``parse_status='parsing'`` overwrite is opt-in and off by default.
        """
        if touch_parse_status:
            await self.session.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(parse_status="parsing")
            )
        await self.delete_for_document(document_id)
        self.session.add_all(list(chunks))
        await self.session.flush()

    async def list_by_document(
        self,
        document_id: UUID | str,
        *,
        include_embeddings: bool = True,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[DocumentChunk]:
        """Unauthenticated full-document chunk list.

        Prefer :meth:`list_authorized_by_document` for any user-facing path.
        Defer vectors when unused to avoid pulling large embedding payloads.
        """
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        if not include_embeddings:
            stmt = stmt.options(defer(DocumentChunk.embedding))
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_authorized_range(
        self,
        *,
        document_id: UUID | str,
        auth: AuthContext,
        start_index: int = 0,
        end_index: int | None = None,
        document_ids_scope: Sequence[UUID] | None = None,
        include_embeddings: bool = False,
        limit: int = 128,
    ) -> list[DocumentChunk]:
        """Authorized chunk index range for one document (neighbor expansion)."""
        if document_ids_scope is not None:
            allowed = {str(item) for item in document_ids_scope}
            if str(document_id) not in allowed:
                return []
        stmt = (
            select(DocumentChunk)
            .join(DocumentChunk.document)
            .options(contains_eager(DocumentChunk.document))
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.chunk_index >= max(0, start_index),
                DocumentRepository.visibility_clause(auth),
            )
            .order_by(DocumentChunk.chunk_index.asc())
            .limit(max(1, limit))
        )
        if end_index is not None:
            stmt = stmt.where(DocumentChunk.chunk_index <= end_index)
        if not include_embeddings:
            stmt = stmt.options(defer(DocumentChunk.embedding))
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_authorized_by_document(
        self,
        *,
        document_id: UUID | str,
        auth: AuthContext,
        document_ids_scope: Sequence[UUID] | None = None,
        limit: int = 128,
    ) -> list[DocumentChunk]:
        """Bounded chunk list for one document under current ACL + optional hard scope."""
        if document_ids_scope is not None:
            allowed = {str(item) for item in document_ids_scope}
            if str(document_id) not in allowed:
                return []

        stmt = (
            select(DocumentChunk)
            .join(DocumentChunk.document)
            .options(contains_eager(DocumentChunk.document))
            .where(
                DocumentChunk.document_id == document_id,
                DocumentRepository.visibility_clause(auth),
            )
            .order_by(DocumentChunk.chunk_index.asc())
            .limit(max(1, limit))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def filter_authorized_document_ids(
        self,
        *,
        document_ids: Sequence[UUID | str],
        auth: AuthContext,
        document_ids_scope: Sequence[UUID] | None = None,
    ) -> set[str]:
        """Return the subset of document IDs currently visible to auth (and in scope)."""
        ids = [str(item) for item in document_ids if item is not None]
        if not ids:
            return set()
        if document_ids_scope is not None:
            scope = {str(item) for item in document_ids_scope}
            ids = [item for item in ids if item in scope]
            if not ids:
                return set()
        stmt = select(Document.id).where(
            Document.id.in_(ids),
            DocumentRepository.visibility_clause(auth),
        )
        result = await self.session.execute(stmt)
        return {str(row[0]) for row in result.all()}

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
        embedding_fingerprint: str | None = None,
    ) -> list[tuple[DocumentChunk, float]]:
        from ...core.config import settings as runtime_settings

        # Selective scopes: exact ordered distance over the candidate set.
        # Broad corpus: tune IVFFlat probes (not a universal lists=100 default).
        exact_cap = int(runtime_settings.PGVECTOR_EXACT_SEARCH_MAX_CANDIDATES)
        selective = bool(document_ids) and len(document_ids) <= max(1, exact_cap // 30)
        if not selective:
            probes = int(runtime_settings.PGVECTOR_IVFFLAT_PROBES)
            await self.session.execute(text(f"SET LOCAL ivfflat.probes = {probes}"))

        distance_expression = DocumentChunk.embedding.cosine_distance(embedding)
        if selective:
            # Deliberately break the ANN operator-ordering match. PostgreSQL must
            # distance-sort the already scoped candidates instead of probing the
            # corpus-wide IVFFlat index and filtering afterward.
            distance_expression = distance_expression + literal_column("0.0")
        distance = distance_expression.label("distance")
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
        if embedding_fingerprint:
            stmt = stmt.where(
                DocumentChunk.metadata_json["embedding_fingerprint"].astext
                == embedding_fingerprint
            )
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
    ) -> list[tuple[DocumentChunk, float]]:
        """Chunks ranked by ``ts_rank_cd`` before LIMIT.

        The float is cover-density rank plus an identifier boost, not BM25.
        """
        normalized_terms = [term.strip() for term in terms if term.strip()]
        if not normalized_terms:
            return []

        vector = self._chunk_tsvector()
        lexical_rank, lexical_match = self._lexical_rank_and_match(
            vector, normalized_terms
        )
        identifier_hit = self._identifier_hit(normalized_terms)
        rank = (lexical_rank + case((identifier_hit, 1.0), else_=0.0)).label(
            "lexical_rank"
        )
        stmt = (
            select(DocumentChunk, rank)
            .join(DocumentChunk.document)
            .options(contains_eager(DocumentChunk.document))
            .where(
                DocumentRepository.visibility_clause(auth),
                or_(lexical_match, identifier_hit),
            )
            .order_by(rank.desc(), DocumentChunk.chunk_index.asc())
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
        return [(row[0], float(row[1] or 0.0)) for row in result.all()]

    @staticmethod
    def _chunk_tsvector():
        config = literal_column(f"'{LEXICAL_REGCONFIG}'::regconfig")
        empty = literal_column("''")
        content = func.setweight(
            func.to_tsvector(config, func.coalesce(DocumentChunk.content, empty)),
            literal_column("'A'"),
        )
        headings = func.setweight(
            func.to_tsvector(
                config,
                func.coalesce(DocumentChunk.section_title, empty)
                + literal_column("' '")
                + func.coalesce(DocumentChunk.heading_path, empty),
            ),
            literal_column("'B'"),
        )
        return content.op("||")(headings)

    @staticmethod
    def _lexical_rank_and_match(vector, terms: Sequence[str]):
        """OR-match safe term queries and sum their cover-density ranks."""
        config = literal_column(f"'{LEXICAL_REGCONFIG}'::regconfig")
        queries = [func.plainto_tsquery(config, term) for term in terms if term]
        if not queries:
            return literal_column("0.0"), Document.id.is_(None)
        ranks = [func.ts_rank_cd(vector, query) for query in queries]
        rank = ranks[0]
        for item in ranks[1:]:
            rank = rank + item
        return rank, or_(*(vector.bool_op("@@")(query) for query in queries))

    @staticmethod
    def _identifier_hit(terms: Sequence[str]):
        clauses = []
        for term in terms:
            if not looks_like_identifier(term):
                continue
            pattern = f"%{term}%"
            clauses.extend(
                [
                    DocumentChunk.content.ilike(pattern),
                    Document.file_name.ilike(pattern),
                    Document.file_path.ilike(pattern),
                ]
            )
        if not clauses:
            return Document.id.is_(None)
        return or_(*clauses)

    @staticmethod
    def _filename_identifier_boost(terms: Sequence[str]):
        clauses = []
        for term in terms:
            pattern = f"%{term}%"
            clauses.append(Document.file_name.ilike(pattern))
            if looks_like_identifier(term):
                clauses.append(Document.file_path.ilike(pattern))
        if not clauses:
            return case((Document.id.is_(None), 1.0), else_=0.0)
        return case((or_(*clauses), 1.0), else_=0.0)

    @classmethod
    def _best_chunk_rank_subquery(cls, terms: Sequence[str]):
        vector = cls._chunk_tsvector()
        rank, lexical_match = cls._lexical_rank_and_match(vector, terms)
        return (
            select(
                DocumentChunk.document_id.label("document_id"),
                func.max(rank).label("lexical_rank"),
            )
            .join(DocumentChunk.document)
            .where(lexical_match)
            .group_by(DocumentChunk.document_id)
            .subquery()
        )

    @classmethod
    def _document_lexical_match(cls, terms: Sequence[str], chunk_rank):
        field_hits = []
        for term in terms:
            pattern = f"%{term}%"
            field_hits.extend(
                [
                    Document.file_name.ilike(pattern),
                    Document.file_path.ilike(pattern),
                    Document.document_type.ilike(pattern),
                    Document.business_domain.ilike(pattern),
                ]
            )
        return or_(chunk_rank.c.document_id.is_not(None), *field_hits)

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
            if parse_status == "indexed":
                # Default searchable set: vector-ready or lexical-only.
                stmt = stmt.where(
                    Document.parse_status.in_(("indexed", "lexical_ready"))
                )
            else:
                stmt = stmt.where(Document.parse_status == parse_status)
        return stmt
