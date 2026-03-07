from __future__ import annotations

from fastapi import APIRouter, Query

from backend.api.deps import CurrentIdentityDep, DbSessionDep
from backend.core.exceptions import NotFoundError
from backend.db.repo.document import DocumentRepository
from backend.schemas.document_schema import DocumentDetail, DocumentRead
from backend.workers.indexing_tasks import enqueue_document_reindex

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/", response_model=list[DocumentRead])
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
    document = await repo.get_with_chunks(document_id)
    if (
        document is None
        or await repo.get_visible_to_auth(document_id, identity.auth) is None
    ):
        raise NotFoundError("Document not found")
    return DocumentDetail.model_validate(document)


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
