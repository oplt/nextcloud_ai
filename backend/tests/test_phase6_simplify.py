"""Phase 6: dead-path removal, shared lexical JSON, filter kwargs, extractor module."""

from __future__ import annotations

import warnings

import pytest

from backend.rag.evidence_extractor import EvidenceExtractor
from backend.rag.lexical import semantic_json_text
from backend.rag.stores import retrieval_filter_kwargs
from backend.schemas.chat_schema import ChatSource, RetrievalFilters


def test_retrieval_filter_kwargs_none() -> None:
    kwargs = retrieval_filter_kwargs(None)
    assert kwargs["connector_ids"] is None
    assert kwargs["source_types"] is None


def test_retrieval_filter_kwargs_populated() -> None:
    from uuid import uuid4

    cid = uuid4()
    filters = RetrievalFilters(connector_ids=[cid], path_prefixes=["/a"])
    kwargs = retrieval_filter_kwargs(filters)
    assert kwargs["connector_ids"] == [cid]
    assert kwargs["path_prefixes"] == ["/a"]


def test_reranker_uses_semantic_json_allowlist() -> None:
    # ContextReranker imports semantic_json_text — no local _json_text.
    import backend.rag.reranker as reranker_mod

    assert not hasattr(reranker_mod, "_json_text")
    text = semantic_json_text(
        {"from": "a@b.c", "stored_payload_b64": "SHOULD_NOT_APPEAR" * 8}
    )
    assert "a@b.c" in text
    assert "SHOULD_NOT_APPEAR" not in text


def test_evidence_extractor_amount() -> None:
    from uuid import uuid4

    source = ChatSource(
        document_id=uuid4(),
        chunk_id=uuid4(),
        file_name="invoice.pdf",
        file_path="/invoice.pdf",
        content="Invoice total 120,50 EUR payable now",
        snippet="Invoice total 120,50 EUR",
        distance=0.1,
        score=0.9,
    )
    matches = EvidenceExtractor.amount_extractor([source])
    assert matches
    assert "120" in matches[0].value


def test_dead_helpers_removed() -> None:
    import backend.db.session as session_mod
    import backend.services.chat_service as chat_mod
    import backend.services.product_intelligence_service as intel_mod
    import backend.workers.indexing_tasks as tasks_mod

    assert not hasattr(session_mod, "run_async_safe")
    assert not hasattr(tasks_mod, "_run_logged_background_task")
    assert not hasattr(intel_mod.ProductIntelligenceService, "_classify_document")
    assert not hasattr(chat_mod.ChatService, "_source_evidence_lines")
    assert not hasattr(chat_mod.ChatService, "_entity_match_score")
    assert not hasattr(EvidenceExtractor, "field_value_extractor")
    assert not hasattr(EvidenceExtractor, "table_row_extractor")


def test_compat_wrappers_emit_deprecation() -> None:
    from backend.parsers.document_parser import parse_odt_bytes
    from backend.services.query_writer import is_likely_follow_up
    from backend.ai.prompt_builder import available_domain_profiles

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert is_likely_follow_up("and the amount?", has_history=True) in {True, False}
        assert isinstance(available_domain_profiles(), tuple)
        # ODT wrapper warns even on invalid payload path — call after warn check on others
        assert any(issubclass(w.category, DeprecationWarning) for w in caught)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(ValueError):
            parse_odt_bytes(b"not-an-odt")
        assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_conversational_rag_and_uow_removed() -> None:
    import importlib.util

    assert (
        importlib.util.find_spec("backend.services.conversational_rag_service") is None
    )
    assert importlib.util.find_spec("backend.db.repo.uow") is None


def test_cleanup_stale_connections_retained_noop() -> None:
    from backend.workers.indexing_tasks import cleanup_stale_connections

    result = cleanup_stale_connections()
    assert result["skipped"] is True
    assert result.get("deprecated") is True
