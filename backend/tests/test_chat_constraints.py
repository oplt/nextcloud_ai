from uuid import uuid4

import pytest

from backend.db.models import Document, DocumentChunk
from backend.schemas.chat_schema import ChatSource
from backend.services.chat_service import ChatService


def _source(content: str) -> ChatSource:
    return ChatSource(
        chunk_id=uuid4(),
        document_id=uuid4(),
        file_name="resume.pdf",
        file_path="/resume.pdf",
        snippet=content,
        content=content,
        score=0.8,
        distance=0.2,
    )


def test_year_filter_relaxes_when_it_would_drop_all_sources() -> None:
    sources = [_source("Ozgur worked as a Python developer in Hasselt.")]

    filtered, debug = ChatService._filter_sources_for_question_constraints(
        question="where did ozgur work in 2005",
        sources=sources,
    )

    assert filtered == sources
    assert debug["time_filter_relaxed"] is True


def test_source_label_citations_are_parsed() -> None:
    sources = [_source("Invoice total is 190,04 EUR.")]

    answer, cited = ChatService._filter_sources_to_citations(
        "The amount is 190,04 EUR [SOURCE 1].",
        sources,
    )

    assert answer == "The amount is 190,04 EUR [1]."
    assert cited == sources


def test_insufficient_answer_keeps_sources_for_panel() -> None:
    sources = [_source("Invoice total is 190,04 EUR.")]
    service = object.__new__(ChatService)

    _answer, cited, verification = service._verify_and_normalize_answer(
        question="what is the invoice amount",
        answer="I could not verify the amount from the retrieved sources.",
        sources=sources,
        shadow_mode=False,
        trace_id="trace",
    )

    assert verification["result"] == "insufficient_answer"
    assert cited == sources


def test_direct_title_answer_is_title_only() -> None:
    source = _source(
        "Journal of Economic Cooperation and Development, 33, 1 (2012), 79-94. "
        "Polat, Ozgur."
    )
    source.file_name = "The Impact of Foreign Trade on the Labor Market- Evidence from Turkish Economy.pdf"

    result = ChatService._build_direct_answer(
        question="what is the name of the article ozgur write in 2012",
        sources=[source],
        trace_id="trace",
    )

    assert result is not None
    answer, cited, verification = result
    assert answer == "The Impact of Foreign Trade on the Labor Market: Evidence from Turkish Economy [1]"
    assert cited == [source]
    assert verification["direct_extraction_type"] == "title"


def test_direct_amount_answer_is_precise() -> None:
    sources = [_source("TE BETALEN VOOR 16/03/2026 190,04 EUR")]

    result = ChatService._build_direct_answer(
        question="what is the invoice amount",
        sources=sources,
        trace_id="trace",
    )

    assert result is not None
    answer, cited, verification = result
    assert answer == "190,04 EUR [1]"
    assert cited == sources
    assert verification["result"] == "direct_extraction"


def test_direct_amount_answer_respects_query_entity() -> None:
    sources = [
        _source("Generic invoice gross total 32.30 EUR."),
        _source("Klantrekening De Watergroep. TE BETALEN VOOR 16/03/2026 190,04 EUR"),
    ]

    result = ChatService._build_direct_answer(
        question="what is the amount of invoice from de watergroup",
        sources=sources,
        trace_id="trace",
    )

    assert result is not None
    answer, cited, _verification = result
    assert answer == "190,04 EUR [1]"
    assert cited == [sources[1]]


def test_direct_due_date_answer_respects_query_entity() -> None:
    sources = [
        _source("Klantrekening De Watergroep. Factuurdatum: 13/02/2026."),
        _source("Klantrekening De Watergroep. TE BETALEN VOOR 16/03/2026 190,04 EUR"),
    ]

    result = ChatService._build_direct_answer(
        question="when is the due date of the invoice from De WaterGroup",
        sources=sources,
        trace_id="trace",
    )

    assert result is not None
    answer, cited, verification = result
    assert answer == "16/03/2026 [1]"
    assert cited == [sources[1]]
    assert verification["direct_extraction_type"] == "due_date"


def test_direct_range_answer_extracts_overlapping_rows() -> None:
    sources = [
        _source("Dicle University | Turkey | Mar 2010 - July 2014"),
        _source("Selahaddin Eyyubi University | Turkey | Mar 2014 - July 2016"),
    ]

    result = ChatService._build_direct_answer(
        question="where did the person work between 2010 and 2015",
        sources=sources,
        trace_id="trace",
    )

    assert result is not None
    answer, cited, verification = result
    assert answer.splitlines() == [
        "- Dicle University (Turkey, Mar 2010 - July 2014) [1]",
        "- Selahaddin Eyyubi University (Turkey, Mar 2014 - July 2016) [2]",
    ]
    assert cited == sources
    assert verification["direct_extraction_type"] == "date_range_rows"


def test_direct_range_answer_rejects_context_bleed_labels() -> None:
    sources = [
        _source(
            "Context above: Delivered lectures. ● Worked with multicultural teams. "
            "Dicle University | Turkey | Mar 2010 - July 2014"
        )
    ]

    result = ChatService._build_direct_answer(
        question="where did the person work between 2010 and 2015",
        sources=sources,
        trace_id="trace",
    )

    assert result is None


class _ChunkRepo:
    async def list_by_document(self, document_id):
        document = Document(
            id=document_id,
            file_name="OzgurPolat_Resume.pdf",
            file_path="/OzgurPolat_Resume.pdf",
            sync_status="synced",
            parse_status="indexed",
            source_type="nextcloud",
            document_type="resume",
            business_domain="hr",
            is_deleted=False,
        )
        return [
            DocumentChunk(
                id=uuid4(),
                document_id=document_id,
                chunk_index=12,
                content="Invoice period | Belgium | Nov 2004 - Mar 2010 | total 190,04 EUR",
                embedding_status="embedded",
                document=document,
            )
        ]


@pytest.mark.asyncio
async def test_same_document_augmentation_adds_relevant_year_range_chunk(monkeypatch) -> None:
    source = _source("Document overview.")
    service = object.__new__(ChatService)
    service.session = object()
    monkeypatch.setattr(
        "backend.services.chat_service.DocumentChunkRepository",
        lambda session: _ChunkRepo(),
    )

    augmented = await service._augment_question_sources_from_same_documents(
        question="what happened in 2005",
        sources=[source],
        max_sources=6,
    )

    assert "Invoice period" in augmented[0].content


@pytest.mark.asyncio
async def test_same_document_augmentation_boosts_money_chunks(monkeypatch) -> None:
    source = _source("Invoice metadata.")
    service = object.__new__(ChatService)
    service.session = object()
    monkeypatch.setattr(
        "backend.services.chat_service.DocumentChunkRepository",
        lambda session: _ChunkRepo(),
    )

    augmented = await service._augment_question_sources_from_same_documents(
        question="what is the invoice amount",
        sources=[source],
        max_sources=6,
    )

    assert "190,04 EUR" in augmented[0].content
