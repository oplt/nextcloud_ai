from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security import AuthContext
from ..db.models import Document
from ..db.repo.document import DocumentRepository
from ..schemas.document_schema import DocumentListRead, DocumentRead


class DocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DocumentRepository(session)

    async def list_documents(
        self,
        *,
        auth: AuthContext,
        query: str | None = None,
        connector_ids: list[str] | None = None,
        mime_types: list[str] | None = None,
        path_prefixes: list[str] | None = None,
        modified_after: datetime | None = None,
        modified_before: datetime | None = None,
        document_type: str | None = None,
        business_domain: str | None = None,
        parse_status: str | None = None,
        source_type: str | None = None,
        needs_review: bool | None = None,
        low_confidence: bool | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> DocumentListRead:
        offset = max(0, (page - 1) * page_size)
        documents = await self.repo.search(
            auth=auth,
            query=query,
            connector_ids=connector_ids,
            mime_types=mime_types,
            path_prefixes=path_prefixes,
            modified_after=modified_after,
            modified_before=modified_before,
            document_type=document_type,
            business_domain=business_domain,
            parse_status=parse_status,
            source_type=source_type,
            needs_review=needs_review,
            low_confidence=low_confidence,
            include_chunks=False,
            offset=offset,
            limit=page_size,
        )
        total = await self.repo.count_search(
            auth=auth,
            query=query,
            connector_ids=connector_ids,
            mime_types=mime_types,
            path_prefixes=path_prefixes,
            modified_after=modified_after,
            modified_before=modified_before,
            document_type=document_type,
            business_domain=business_domain,
            parse_status=parse_status,
            source_type=source_type,
            needs_review=needs_review,
            low_confidence=low_confidence,
        )
        chunk_count_map = await self.repo.count_chunks_by_document_ids(
            [document.id for document in documents]
        )

        return DocumentListRead(
            items=[
                _document_read(
                    document,
                    chunk_count=chunk_count_map.get(str(document.id), 0),
                )
                for document in documents
            ],
            total=total,
            page=page,
            page_size=page_size,
        )


def _signal_counts(document: Document) -> dict[str, int]:
    payload = document.intelligence_json or {}
    counts: dict[str, int] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            counts[key] = sum(len(v) for v in value.values() if isinstance(v, list))
        elif isinstance(value, list):
            counts[key] = len(value)
    return counts


def _needs_review(document: Document) -> bool:
    return (
        document.parse_status in {"failed", "needs_ocr", "unsupported_type"}
        or document.document_type == "unclassified"
        or document.business_domain == "unknown"
        or (document.document_type_confidence or 0.0) < 0.6
        or (document.business_domain_confidence or 0.0) < 0.6
    )


def _document_read(document: Document, *, chunk_count: int) -> DocumentRead:
    metadata = dict(document.metadata_json or {})
    return DocumentRead.model_validate(
        {
            **document.__dict__,
            "chunk_count": chunk_count,
            "ingestion_quality": metadata.get("ingestion_quality"),
            "signal_counts": _signal_counts(document),
            "needs_review": _needs_review(document),
        }
    )
