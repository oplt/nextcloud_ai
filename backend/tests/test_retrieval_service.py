from uuid import uuid4

from backend.db.models import Document, DocumentChunk
from backend.rag.stores import RetrievalCandidate
from backend.services.retrieval_service import RetrievalService


def _chunk(*, score: float) -> RetrievalCandidate:
    document_id = uuid4()
    document = Document(
        id=document_id,
        file_path="/Invoices/acme.pdf",
        file_name="acme.pdf",
        sync_status="synced",
        parse_status="parsed",
        source_type="nextcloud",
        document_type="invoice",
        business_domain="finance",
        is_deleted=False,
    )
    chunk = DocumentChunk(
        id=uuid4(),
        document_id=document_id,
        chunk_index=0,
        content="ACME invoice total is 123.45 EUR.",
        embedding_status="embedded",
        document=document,
    )
    return RetrievalCandidate(chunk=chunk, semantic_score=score)


def test_broad_retrieval_keeps_absolute_score_floor() -> None:
    candidate = _chunk(score=0.2)
    service = object.__new__(RetrievalService)

    selected = service._select_grounded_chunks(
        ranked_chunks=[candidate],
        keyword_terms=["amount"],
        top_k=3,
    )

    assert selected == []


def test_scoped_retrieval_returns_best_chunk_below_score_floor() -> None:
    candidate = _chunk(score=0.2)
    service = object.__new__(RetrievalService)

    selected = service._select_grounded_chunks(
        ranked_chunks=[candidate],
        keyword_terms=["amount"],
        top_k=3,
        allow_scoped_fallback=True,
    )

    assert selected == [(candidate.chunk, 0.2)]
