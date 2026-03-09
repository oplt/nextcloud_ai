from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Query, Response

from backend.api.deps import CurrentIdentityDep, DbSessionDep
from backend.connectors.nextcloud.client import AsyncNextcloudClient
from backend.core.exceptions import NotFoundError
from backend.db.repo.connector import ConnectorRepository
from backend.db.repo.document import DocumentRepository
from backend.schemas.document_schema import DocumentDetail, DocumentRead
from backend.services.connector_service import ConnectorService
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
        identity: CurrentIdentityDep,
        query: str | None = Query(default=None),
        connector_id: str | None = Query(default=None),
) -> list[DocumentRead]:
    repo = DocumentRepository(session)
    documents = await repo.search(
        auth=identity.auth, query=query, connector_id=connector_id, limit=100
    )
    return [DocumentRead.model_validate(document) for document in documents]


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
        document_id: str, session: DbSessionDep, identity: CurrentIdentityDep
) -> DocumentDetail:
    repo = DocumentRepository(session)
    document = await repo.get_with_chunks_visible_to_auth(document_id, identity.auth)
    if document is None:
        raise NotFoundError("Document not found")
    return DocumentDetail.model_validate(document)


@router.get("/{document_id}/original")
async def get_document_original(
        document_id: str, session: DbSessionDep, identity: CurrentIdentityDep
) -> Response:
    document_repo = DocumentRepository(session)
    document = await document_repo.get_visible_to_auth(document_id, identity.auth)
    if document is None:
        raise NotFoundError("Document not found")

    connector = await ConnectorRepository(session).get(str(document.connector_id))
    if connector is None:
        raise NotFoundError("Connector not found")

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
        document_id: str, session: DbSessionDep, identity: CurrentIdentityDep
) -> dict[str, str]:
    repo = DocumentRepository(session)
    document = await repo.get_visible_to_auth(document_id, identity.auth)
    if document is None:
        raise NotFoundError("Document not found")
    task = enqueue_document_reindex(str(document.id))
    return {"status": "queued", "task_id": task.id, "document_id": str(document.id)}
