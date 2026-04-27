from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from backend.schemas.chat_schema import ChatSource
from backend.services.chat_service import ChatService


def _article_source() -> ChatSource:
    return ChatSource(
        chunk_id=uuid4(),
        document_id=uuid4(),
        file_name="The Impact of Foreign Trade on the Labor Market: Evidence from Turkish Economy.pdf",
        file_path="/articles/The Impact of Foreign Trade on the Labor Market: Evidence from Turkish Economy.pdf",
        page_number=1,
        section_title="Abstract",
        snippet="Published article by Ozgur Polat in 2012. Abstract: This paper studies foreign trade and labor market outcomes.",
        distance=0.1,
        score=0.92,
        heading_path="Abstract",
        content="Published article by Ozgur Polat in 2012. Abstract: This paper studies foreign trade and labor market outcomes.",
    )


def test_summary_request_uses_extractive_summary_shortcut() -> None:
    source = _article_source().model_copy(
        update={
            "section_title": "Abstract",
            "heading_path": "Abstract",
            "content": (
                "This paper analyzes the impact of foreign trade on labor market outcomes by using "
                "random coefficient panel data analysis and quarterly data from manufacturing sectors. "
                "The results showed that production had a positive impact on labor whereas it had a "
                "negative impact on wages. Imports and exports also had significant positive impacts "
                "on employment and wages in the indexed results."
            ),
        }
    )

    result = ChatService._build_direct_answer(
        question="summarize the article that Ozgur Polat write in 2012",
        sources=[source],
        trace_id="test-trace",
    )

    assert result is not None
    answer, sources, summary = result
    assert "This paper analyzes the impact of foreign trade" in answer
    assert sources == [source]
    assert summary["direct_extraction_type"] == "summary"


def test_summary_request_with_metadata_only_does_not_use_title_shortcut() -> None:
    result = ChatService._build_direct_answer(
        question="summarize the article that Ozgur Polat write in 2012",
        sources=[_article_source()],
        trace_id="test-trace",
    )

    assert result is None


def test_summary_request_gets_summary_specific_prompt_rules() -> None:
    rules = ChatService._answer_style_rules("summarize the article that Ozgur Polat write in 2012")

    assert any("summarize the source content itself" in rule for rule in rules)
    assert any("do not answer by only naming the title" in rule for rule in rules)


def test_title_only_summary_answer_is_rejected() -> None:
    service = object.__new__(ChatService)
    source = _article_source()

    answer, sources, summary = service._verify_and_normalize_answer(
        question="summarize the article that Ozgur Polat write in 2012",
        answer='The article written by Ozgur Polat in 2012 is "The Impact of Foreign Trade on the Labor Market: Evidence from Turkish Economy" [1].',
        sources=[source],
        shadow_mode=False,
        trace_id="test-trace",
    )

    assert "could not verify enough article content" in answer
    assert sources == [source]
    assert summary["result"] == "summary_title_only"


def test_title_only_summary_answer_falls_back_to_extractive_summary() -> None:
    service = object.__new__(ChatService)
    source = _article_source().model_copy(
        update={
            "section_title": "Abstract",
            "heading_path": "Abstract",
            "content": (
                "This paper analyzes the impact of foreign trade on labor market outcomes by using "
                "random coefficient panel data analysis and quarterly data from manufacturing sectors. "
                "The results showed that production had a positive impact on labor whereas it had a "
                "negative impact on wages. Imports and exports also had significant positive impacts "
                "on employment and wages in the indexed results."
            ),
        }
    )

    answer, sources, summary = service._verify_and_normalize_answer(
        question="summarize the article that Ozgur Polat write in 2012",
        answer='The article written by Ozgur Polat in 2012 is "The Impact of Foreign Trade on the Labor Market: Evidence from Turkish Economy" [1].',
        sources=[source],
        shadow_mode=False,
        trace_id="test-trace",
    )

    assert "This paper analyzes the impact of foreign trade" in answer
    assert "production had a positive impact" in answer
    assert sources == [source]
    assert summary["result"] == "summary_extractive_fallback"


def test_summary_sentence_cleaning_removes_pdf_heading_prefix() -> None:
    cleaned = ChatService._clean_summary_sentence(
        "Evidence from Turkish Economy > The results of estimations show that impact of production on employment is positive."
    )

    assert cleaned == "The results of estimations show that impact of production on employment is positive."


def test_summary_chunk_relevance_prefers_article_body_sections() -> None:
    source = _article_source().model_copy(update={"section_title": "Abstract", "heading_path": "Abstract"})
    chunk = SimpleNamespace(
        content=" ".join(["foreign trade affects labor market outcomes"] * 35),
        section_title="Abstract",
        heading_path="Abstract",
        chunk_index=0,
    )

    assert ChatService._summary_chunk_relevance(source=source, chunk=chunk) > 6


def test_summary_chunk_relevance_ignores_tiny_metadata_chunks() -> None:
    source = _article_source().model_copy(update={"section_title": "Title", "heading_path": "Title"})
    chunk = SimpleNamespace(
        content="The Impact of Foreign Trade on the Labor Market",
        section_title="Title",
        heading_path="Title",
        chunk_index=0,
    )

    assert ChatService._summary_chunk_relevance(source=source, chunk=chunk) == 0


def test_title_request_still_uses_title_shortcut() -> None:
    source = _article_source()
    result = ChatService._build_direct_answer(
        question="what article did Ozgur Polat write in 2012",
        sources=[source],
        trace_id="test-trace",
    )

    assert result is not None
    answer, sources, summary = result
    assert answer == "The Impact of Foreign Trade on the Labor Market: Evidence from Turkish Economy [1]"
    assert sources == [source]
    assert summary["direct_extraction_type"] == "title"
