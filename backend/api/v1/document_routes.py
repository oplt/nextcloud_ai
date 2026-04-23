from __future__ import annotations

import base64
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response

from backend.api.deps import AuthenticatedUser, DbSessionDep, permission_required
from backend.connectors.nextcloud.client import AsyncNextcloudClient
from backend.core.exceptions import NotFoundError
from backend.db.repo.connector import ConnectorRepository
from backend.db.repo.document import DocumentRepository
from backend.schemas.document_schema import DocumentDetail, DocumentRead
from backend.services.authorization_service import parse_csv_query_values
from backend.services.connector_service import ConnectorService
from backend.services.product_intelligence_service import ProductIntelligenceService
from backend.workers.indexing_tasks import enqueue_document_reindex

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
        limit=100,
    )
    return [DocumentRead.model_validate(document) for document in documents]


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
    return await ProductIntelligenceService(session).build_document_detail(document=document)


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
