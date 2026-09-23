"""Phase 4 lexical contract: ts_rank_cd, allowlist, catalog intent."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from backend.db.repo.document import DocumentChunkRepository, DocumentRepository
from backend.rag.lexical import (
    classify_catalog_intent,
    semantic_json_text,
    squash_ts_rank,
)
from backend.rag.stores import bm25_score_chunks
from backend.services.document_search_service import DocumentSearchService


def test_semantic_json_drops_keys_and_base64() -> None:
    blob = "A" * 80
    text = semantic_json_text(
        {
            "subject": "Invoice 1042",
            "acl_blob": "secret-principal",
            "attachment_b64": blob,
            "nested": {"vendor": "Acme", "etag": "deadbeef"},
        }
    )
    assert "Invoice 1042" in text
    assert "Acme" in text
    assert "secret-principal" not in text
    assert "acl_blob" not in text
    assert "etag" not in text
    assert blob not in text


def test_catalog_intent_splits_navigation_from_enumeration() -> None:
    assert classify_catalog_intent("find the acme invoice") == "navigation"
    assert (
        DocumentSearchService.is_document_discovery_query("find the acme invoice")
        is True
    )
    assert classify_catalog_intent("what is the payment term") == "factual"
    assert (
        DocumentSearchService.is_document_discovery_query("list the payment terms")
        is False
    )
    assert classify_catalog_intent("list all invoices") == "exhaustive"
    assert DocumentSearchService.is_exhaustive_catalog_query("how many contracts")
    assert (
        DocumentSearchService.is_document_discovery_query("how many contracts") is False
    )


def test_squash_ts_rank_keeps_order_and_zero() -> None:
    assert squash_ts_rank(0) == 0
    assert squash_ts_rank(1) > squash_ts_rank(0.2)
    assert squash_ts_rank(1) < 1


def test_overlap_score_has_no_window_idf() -> None:
    weak = SimpleNamespace(
        content="invoice",
        section_title="",
        heading_path="",
        document=SimpleNamespace(
            file_name="a.pdf",
            file_path="/a.pdf",
            document_type="invoice",
            business_domain="finance",
            metadata_json={"acl": "hidden-token"},
            extracted_fields_json={},
        ),
    )
    strong = SimpleNamespace(
        content="invoice invoice invoice",
        section_title="",
        heading_path="",
        document=weak.document,
    )
    # Same relative coverage: one distinct query term present. No IDF boost
    # from a tiny candidate window.
    left = bm25_score_chunks(["invoice"], [weak])
    right = bm25_score_chunks(["invoice"], [weak, strong])
    assert left[0][1] == right[0][1]
    tokens_source = " ".join(
        [
            weak.content,
            semantic_json_text(weak.document.metadata_json),
        ]
    )
    assert "hidden-token" not in tokens_source


def test_keyword_sql_ranks_before_limit_and_skips_raw_json() -> None:
    from backend.core.security import AuthContext
    from sqlalchemy import case, func, or_, select

    from backend.db.models import Document, DocumentChunk
    from backend.rag.lexical import LEXICAL_REGCONFIG

    vector = DocumentChunkRepository._chunk_tsvector()
    tsquery = func.plainto_tsquery(LEXICAL_REGCONFIG, "invoice 1042")
    rank = func.ts_rank_cd(vector, tsquery)
    rank_sql = str(rank.compile(dialect=postgresql.dialect()))
    assert "ts_rank_cd" in rank_sql
    assert "metadata_json" not in rank_sql
    auth = AuthContext(user_id="u1", auth_provider="local", is_superuser=True)
    identifier_hit = Document.id.is_(None)
    labeled = (rank + case((identifier_hit, 1.0), else_=0.0)).label("lexical_rank")
    stmt = (
        select(DocumentChunk.id, labeled)
        .join(DocumentChunk.document)
        .where(
            DocumentRepository.visibility_clause(auth),
            or_(vector.op("@@")(tsquery), identifier_hit),
        )
        .order_by(labeled.desc(), DocumentChunk.chunk_index.asc())
        .limit(8)
    )
    built = str(stmt.compile(dialect=postgresql.dialect()))
    assert "ts_rank_cd" in built
    assert built.lower().rfind("order by") < built.lower().rfind("limit")


def test_weighted_fts_expression_is_indexable_and_terms_match_with_or() -> None:
    vector = DocumentChunkRepository._chunk_tsvector()
    rank, match = DocumentChunkRepository._lexical_rank_and_match(
        vector, ["invoice", "INV-1042"]
    )
    vector_sql = str(vector.compile(dialect=postgresql.dialect()))
    match_sql = str(match.compile(dialect=postgresql.dialect()))
    rank_sql = str(rank.compile(dialect=postgresql.dialect()))
    assert "setweight" in vector_sql
    assert "section_title" in vector_sql
    assert "file_name" not in vector_sql
    assert " OR " in match_sql
    assert rank_sql.count("ts_rank_cd") == 2

    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/e5f6a7b8c9d0_align_weighted_fts_index.py"
    ).read_text(encoding="utf-8")
    assert "USING gin ((" in migration


def test_content_score_uses_sql_rank_not_chunk_prefix() -> None:
    service = DocumentSearchService.__new__(DocumentSearchService)
    document = SimpleNamespace(
        file_name="late.pdf",
        file_path="/late.pdf",
        document_type="memo",
        business_domain="ops",
        metadata_json={"subject": "alpha"},
        extracted_fields_json={},
        chunks=[],
    )
    scored = service._score_document(document, ["zeta"], lexical_rank=0.4)
    assert "content" in scored.matched_fields
    assert scored.score >= 0.4


def test_document_search_sql_limits_documents_not_chunk_rows() -> None:
    chunk_rank = DocumentChunkRepository._best_chunk_rank_subquery(["acme"])
    sql = str(chunk_rank.compile(dialect=postgresql.dialect()))
    assert "max" in sql.lower()
    assert "ts_rank_cd" in sql
    assert "group by" in sql.lower()
    assert "limit" not in sql.lower()
