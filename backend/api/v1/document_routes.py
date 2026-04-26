from __future__ import annotations

import base64
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response

from ..deps import AuthenticatedUser, DbSessionDep, permission_required
from ...connectors.nextcloud.client import AsyncNextcloudClient
from ...core.exceptions import BadRequestError, NotFoundError
from ...db.repo.connector import ConnectorRepository
from ...db.repo.document import DocumentRepository
from ...ingestion.taxonomy import BUSINESS_DOMAINS, DOCUMENT_TYPES, PARSE_STATUSES
from ...schemas.document_schema import (
    DocumentClassificationPatch,
    DocumentDetail,
    DocumentRead,
    DocumentTaxonomyRead,
)
from ...services.authorization_service import parse_csv_query_values
from ...services.connector_service import ConnectorService
from ...services.product_intelligence_service import ProductIntelligenceService
from ...workers.indexing_tasks import enqueue_document_reindex

router = APIRouter(prefix="/documents", tags=["documents"])


def build_content_disposition(filename: str, disposition: str = "inline") -> str:
    fallback = (
        filename.encode("ascii", "ignore").decode("ascii").replace("\\", "_").replace('"', "")
    ).strip() or "document"
    encoded = quote(filename, safe="")
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


@router.get("", response_model=list[DocumentRead])
async def list_documents(
        session: DbSessionDep,
        identity: AuthenticatedUser = Depends(permission_required("documents:read")),
        query: str | None = Query(default=None),
        connector_id: list[str] | None = Query(default=None),
        mime_type: list[str] | None = Query(default=None),
        path_prefix: list[str] | None = Query(default=None),
        modified_after: datetime | None = Query(default=None),
        modified_before: datetime | None = Query(default=None),
        document_type: str | None = Query(default=None),
        business_domain: str | None = Query(default=None),
        parse_status: str | None = Query(default=None),
        source_type: str | None = Query(default=None),
        needs_review: bool | None = Query(default=None),
        low_confidence: bool | None = Query(default=None),
) -> list[DocumentRead]:
    repo = DocumentRepository(session)
    documents = await repo.search(
        auth=identity.auth,
        query=query,
        connector_ids=parse_csv_query_values(connector_id),
        mime_types=parse_csv_query_values(mime_type),
        path_prefixes=parse_csv_query_values(path_prefix),
        modified_after=modified_after,
        modified_before=modified_before,
        document_type=document_type,
        business_domain=business_domain,
        parse_status=parse_status,
        source_type=source_type,
        needs_review=needs_review,
        low_confidence=low_confidence,
        limit=100,
    )
    return [_document_read(document) for document in documents]


@router.get("/taxonomy", response_model=DocumentTaxonomyRead)
async def get_document_taxonomy(
        identity: AuthenticatedUser = Depends(permission_required("documents:read")),
) -> DocumentTaxonomyRead:
    return DocumentTaxonomyRead(
        document_types=DOCUMENT_TYPES,
        business_domains=BUSINESS_DOMAINS,
        parse_statuses=PARSE_STATUSES,
    )


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
        document_id: str,
        session: DbSessionDep,
        identity: AuthenticatedUser = Depends(permission_required("documents:read")),
) -> DocumentDetail:
    repo = DocumentRepository(session)
    document = await repo.get_with_chunks_visible_to_auth(document_id, identity.auth)
    if document is None:
        raise NotFoundError("Document not found")
    return _document_detail(
        await ProductIntelligenceService(session).build_document_detail(document=document)
    )


@router.patch("/{document_id}/classification", response_model=DocumentDetail)
async def patch_document_classification(
        document_id: str,
        payload: DocumentClassificationPatch,
        session: DbSessionDep,
        identity: AuthenticatedUser = Depends(permission_required("documents:reindex")),
) -> DocumentDetail:
    if payload.document_type not in DOCUMENT_TYPES:
        raise BadRequestError("Unknown document type")
    if payload.business_domain not in BUSINESS_DOMAINS:
        raise BadRequestError("Unknown business domain")
    repo = DocumentRepository(session)
    document = await repo.get_with_chunks_visible_to_auth(document_id, identity.auth)
    if document is None:
        raise NotFoundError("Document not found")
    previous = {
        "document_type": document.document_type,
        "document_type_confidence": document.document_type_confidence,
        "document_type_reason": document.document_type_reason,
        "business_domain": document.business_domain,
        "business_domain_confidence": document.business_domain_confidence,
        "business_domain_reason": document.business_domain_reason,
    }
    document.document_type = payload.document_type
    document.document_type_confidence = 1.0
    document.document_type_reason = payload.document_type_reason or f"Manual override. Previous: {previous}"
    document.document_type_source = "manual"
    document.business_domain = payload.business_domain
    document.business_domain_confidence = 1.0
    document.business_domain_reason = payload.business_domain_reason or f"Manual override. Previous: {previous}"
    document.business_domain_source = "manual"
    document.manual_category_override = True
    document.classified_at = datetime.now(timezone.utc)
    await session.flush()
    detail = await ProductIntelligenceService(session).build_document_detail(document=document)
    return _document_detail(detail)


@router.get("/{document_id}/original")
async def get_document_original(
        document_id: str,
        session: DbSessionDep,
        identity: AuthenticatedUser = Depends(permission_required("documents:read")),
) -> Response:
    document_repo = DocumentRepository(session)
    document = await document_repo.get_visible_to_auth(document_id, identity.auth)
    if document is None:
        raise NotFoundError("Document not found")

    metadata = dict(document.metadata_json or {})
    stored_payload_b64 = metadata.get("stored_payload_b64")
    if isinstance(stored_payload_b64, str) and stored_payload_b64:
        payload = base64.b64decode(stored_payload_b64)
        return Response(
            content=payload,
            media_type=document.mime_type or "application/octet-stream",
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": build_content_disposition(document.file_name),
                "Content-Length": str(len(payload)),
            },
        )

    connector = await ConnectorRepository(session).get(str(document.connector_id))
    if connector is None:
        raise NotFoundError("Connector not found")
    if (connector.connector_type or "nextcloud") != "nextcloud":
        raise NotFoundError("Original payload is not available for this document")

    client = AsyncNextcloudClient(ConnectorService(session).build_config(connector))
    try:
        payload = await client.download_file(document.file_path)
    finally:
        await client.aclose()

    return Response(
        content=payload,
        media_type=document.mime_type or "application/octet-stream",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": build_content_disposition(document.file_name),
            "Content-Length": str(len(payload)),
        },
    )


@router.post("/{document_id}/reindex")
async def reindex_document(
        document_id: str,
        session: DbSessionDep,
        identity: AuthenticatedUser = Depends(permission_required("documents:reindex")),
) -> dict[str, str]:
    repo = DocumentRepository(session)
    document = await repo.get_visible_to_auth(document_id, identity.auth)
    if document is None:
        raise NotFoundError("Document not found")
    task = enqueue_document_reindex(str(document.id))
    return {"status": "queued", "task_id": task.id, "document_id": str(document.id)}


def _signal_counts(document) -> dict[str, int]:
    payload = document.intelligence_json or {}
    counts: dict[str, int] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            counts[key] = sum(len(v) for v in value.values() if isinstance(v, list))
        elif isinstance(value, list):
            counts[key] = len(value)
    return counts


def _needs_review(document) -> bool:
    return (
        document.parse_status in {"failed", "needs_ocr", "unsupported_type"}
        or document.document_type == "unclassified"
        or document.business_domain == "unknown"
        or (document.document_type_confidence or 0.0) < 0.6
        or (document.business_domain_confidence or 0.0) < 0.6
    )


def _document_read(document) -> DocumentRead:
    metadata = dict(document.metadata_json or {})
    return DocumentRead.model_validate(
        {
            **document.__dict__,
            "chunk_count": len(getattr(document, "chunks", []) or []),
            "ingestion_quality": metadata.get("ingestion_quality"),
            "signal_counts": _signal_counts(document),
            "needs_review": _needs_review(document),
        }
    )


def _document_detail(document: DocumentDetail) -> DocumentDetail:
    payload = document.model_dump()
    metadata = dict(payload.get("metadata_json") or {})
    payload["chunk_count"] = len(document.chunks)
    payload["ingestion_quality"] = metadata.get("ingestion_quality")
    payload["signal_counts"] = _signal_counts(document)
    payload["needs_review"] = _needs_review(document)
    return DocumentDetail.model_validate(payload)
