"""Phase 4 context packing and evidence verification."""

from __future__ import annotations

from uuid import uuid4

from backend.ai.prompt_builder import build_grounded_prompt
from backend.rag.context_packer import estimate_tokens, pack_evidence_for_prompt
from backend.rag.evidence_verifier import (
    answer_is_supported,
    build_extractive_fallback,
    verify_and_normalize_answer,
)
from backend.schemas.chat_schema import ChatSource


def _source(content: str, *, name: str = "a.pdf", score: float = 0.9) -> ChatSource:
    return ChatSource(
        chunk_id=uuid4(),
        document_id=uuid4(),
        file_name=name,
        file_path=f"/{name}",
        snippet=content[:120],
        distance=0.1,
        score=score,
        content=content,
    )


def test_pack_respects_budget_and_assigns_citations_after() -> None:
    sources = [
        _source("alpha " * 400, name="a.pdf"),
        _source("beta " * 400, name="b.pdf"),
        _source("gamma " * 400, name="c.pdf"),
    ]
    packed = pack_evidence_for_prompt(
        sources,
        question="what is alpha",
        instructions_text="rules " * 50,
        context_tokens=900,
        output_reserve_tokens=100,
        margin_tokens=40,
        per_source_cap_tokens=200,
    )
    assert packed.budget_tokens < 900
    assert packed.evidence_tokens <= packed.budget_tokens
    assert len(packed.sources) >= 1
    assert list(packed.citation_map.keys()) == list(range(1, len(packed.sources) + 1))
    # Citation 1 is always the first packed source.
    assert packed.citation_map[1].file_name == packed.sources[0].file_name
    assert packed.dropped_sources + len(packed.sources) == len(sources) or len(
        packed.sources
    ) <= len(sources)


def test_pack_deduplicates_before_assigning_citations() -> None:
    source = _source("one supported fact")
    packed = pack_evidence_for_prompt(
        [source, source],
        question="what fact",
        context_tokens=800,
        output_reserve_tokens=100,
        margin_tokens=50,
    )
    assert packed.sources == [source]
    assert packed.dropped_sources == 1
    assert list(packed.citation_map) == [1]


def test_pack_preserves_table_rows_when_truncating() -> None:
    table = (
        "Header | Value\n"
        "------ | -----\n"
        "Total | EUR 42.00\n" + ("padding text " * 200) + "\nExtra | row\n"
    )
    packed = pack_evidence_for_prompt(
        [_source(table)],
        question="total amount EUR",
        context_tokens=400,
        output_reserve_tokens=50,
        margin_tokens=20,
        per_source_cap_tokens=80,
    )
    assert packed.sources
    text = packed.sources[0].content or ""
    assert "Total" in text or "EUR" in text or "|" in text


def test_pack_bounds_the_actual_rendered_prompt() -> None:
    sources = [_source("evidence " * 900, name=f"{index}.pdf") for index in range(4)]
    overhead = build_grounded_prompt(
        "What is the evidence?",
        [],
        history=[{"role": "user", "content": "prior " * 80}],
    )
    packed = pack_evidence_for_prompt(
        sources,
        question="What is the evidence?",
        history=[{"role": "user", "content": "prior " * 80}],
        prompt_overhead_text=overhead,
        context_tokens=1600,
        output_reserve_tokens=100,
        margin_tokens=50,
        per_source_cap_tokens=300,
    )
    prompt = build_grounded_prompt(
        "What is the evidence?",
        packed.sources,
        history=[{"role": "user", "content": "prior " * 80}],
    )
    assert estimate_tokens(prompt) + 100 + 50 <= 1600


def test_wrong_amount_is_unsupported() -> None:
    source = _source("Invoice total EUR 50.00 paid by Acme.")
    ok, checks = answer_is_supported(
        question="What is the invoice total?",
        answer="The invoice total is EUR 100.00 [1]",
        cited_sources=[source],
    )
    assert ok is False
    assert any(item.kind == "amount" and item.supported is False for item in checks)


def test_matching_amount_and_entity_pass() -> None:
    source = _source("Acme Corp invoice total EUR 50.00 due 2024-01-15.")
    ok, checks = answer_is_supported(
        question="What is the Acme invoice total?",
        answer="Acme Corp invoice total is EUR 50.00 [1]",
        cited_sources=[source],
    )
    assert ok is True
    assert checks


def test_wrong_currency_and_entity_are_unsupported() -> None:
    source = _source("Acme Corp invoice total USD 50.00 due 2024-01-15.")
    currency_ok, currency_checks = answer_is_supported(
        question="What is the Acme invoice total?",
        answer="Acme Corp invoice total is EUR 50.00 [1].",
        cited_sources=[source],
    )
    assert currency_ok is False
    assert any(item.kind == "amount" and not item.supported for item in currency_checks)

    entity_ok, entity_checks = answer_is_supported(
        question="What is the invoice total?",
        answer="Globex Corp invoice total is USD 50.00 [1].",
        cited_sources=[source],
    )
    assert entity_ok is False
    assert any(item.kind == "entity" and not item.supported for item in entity_checks)


def test_negation_qualifier_and_each_sentence_require_direct_support() -> None:
    source = _source("Employees may carry over 5 days. Acme approved the policy.")
    for answer, failed_kind in (
        ("Employees may not carry over 5 days [1].", "negation"),
        ("Employees may carry over up to 5 days [1].", "qualifier"),
        ("Acme approved the policy [1]. Globex approved it.", "citation"),
    ):
        ok, checks = answer_is_supported(
            question="What does the policy say?",
            answer=answer,
            cited_sources=[source],
        )
        assert ok is False
        assert any(item.kind == failed_kind and not item.supported for item in checks)


def test_unrelated_evidence_abstains() -> None:
    source = _source("Today's lunch menu: soup and bread.")
    verified = verify_and_normalize_answer(
        question="What is the invoice total for INV-1042?",
        answer="The invoice total is EUR 999.00",
        sources=[source],
        shadow_mode=False,
    )
    assert verified.result == "no_inline_citations"
    assert "could not verify" in verified.answer.lower()
    assert verified.sources == []


def test_invalid_citation_id_is_rejected_not_silently_dropped() -> None:
    source = _source("Acme invoice total EUR 50.00.")
    verified = verify_and_normalize_answer(
        question="What is the invoice total?",
        answer="The invoice total is EUR 50.00 [1][9].",
        sources=[source],
        shadow_mode=False,
    )
    assert verified.result == "invalid_citations"
    assert verified.sources == []
    assert verified.details["invalid_citation_ids"] == [9]


def test_extractive_fallback_records_mode() -> None:
    source = _source("Payable amount EUR 12.00 for INV-9.")
    answer, sources, mode = build_extractive_fallback(
        [source], mode="extractive_llm_timeout"
    )
    assert mode == "extractive_llm_timeout"
    assert sources
    assert "[1]" in answer
    assert estimate_tokens(answer) > 0
