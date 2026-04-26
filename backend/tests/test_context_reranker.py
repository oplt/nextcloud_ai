from uuid import uuid4

from backend.db.models import Document, DocumentChunk
from backend.rag.reranker import ContextReranker
from backend.rag.stores import RetrievalCandidate


def _candidate(content: str) -> RetrievalCandidate:
    document = Document(
        id=uuid4(),
        file_name="records.pdf",
        file_path="/records.pdf",
        sync_status="synced",
        parse_status="indexed",
        source_type="nextcloud",
        document_type="record",
        business_domain="general",
        is_deleted=False,
    )
    chunk = DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        chunk_index=0,
        content=content,
        embedding_status="embedded",
        document=document,
    )
    return RetrievalCandidate(chunk=chunk, keyword_score=0.4)


def test_reranker_boosts_range_for_requested_year() -> None:
    intro = _candidate("General document introduction.")
    ranged = _candidate("Service period | Belgium | Nov 2004 - Mar 2010")

    ranked = ContextReranker().rerank(
        question="what happened in 2005",
        keyword_terms=["happened", "2005"],
        candidates=[intro, ranged],
    )

    assert ranked[0] is ranged


def test_reranker_boosts_money_chunk_for_amount_question() -> None:
    tariff = _candidate("Tariff information: base rate is EUR 2,50 per unit.")
    total = _candidate("Invoice summary: total payable amount is 190,04 EUR.")

    ranked = ContextReranker().rerank(
        question="what is the invoice amount",
        keyword_terms=["invoice", "amount"],
        candidates=[tariff, total],
    )

    assert ranked[0] is total


def test_reranker_boosts_due_date_chunk_for_due_question() -> None:
    invoice_date = _candidate("Klantrekening De Watergroep. Factuurdatum: 13/02/2026.")
    due_date = _candidate("Klantrekening De Watergroep. TE BETALEN VOOR 16/03/2026 190,04 EUR.")

    ranked = ContextReranker().rerank(
        question="when is the due date of the invoice from De WaterGroup",
        keyword_terms=["due", "date", "invoice", "watergroup"],
        candidates=[invoice_date, due_date],
    )

    assert ranked[0] is due_date
