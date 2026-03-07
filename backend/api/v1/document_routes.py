from __future__ import annotations

from fastapi import APIRouter

from backend.api.deps import CurrentUserDep, DbSessionDep
from backend.db.repo.document import DocumentRepository
from backend.schemas.document_schema import DocumentRead

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/", response_model=list[DocumentRead])
async def list_documents(
        session: DbSessionDep,
        _: CurrentUserDep,
):
    repo = DocumentRepository(session)

    docs = await repo.search(limit=100)

    return [DocumentRead.model_validate(d) for d in docs]


@router.get("/", response_model=list[DocumentRead])
async def list_documents(
        session: DbSessionDep,
        _: CurrentUserDep,
):
    repo = DocumentRepository(session)

    docs = await repo.search(limit=100)

    return [DocumentRead.model_validate(d) for d in docs]


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
        document_id: str,
        session: DbSessionDep,
        _: CurrentUserDep,
):
    repo = DocumentRepository(session)
    doc = await repo.get(document_id)

    if not doc:
        raise ValueError("Document not found")

    return DocumentRead.model_validate(doc)


@router.post("/{document_id}/index")
async def index_document(
        document_id: str,
        session: DbSessionDep,
        _: CurrentUserDep,
):

    from backend.services.indexing_service import IndexingService

    service = IndexingService(session)

    await service.index_document(document_id)

    return {"status": "indexed"}