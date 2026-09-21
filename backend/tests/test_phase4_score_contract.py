"""Phase 4 score contract: RRF, None≠0, sigmoid, no lexical undo, abstention."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from backend.ai.rag_postprocess import rerank_and_truncate_sources, rerank_sources_lexically
from backend.rag.cross_encoder_reranker import CrossEncoderReranker
from backend.rag.retriever import merge_candidates_rrf
from backend.rag.stores import RetrievalCandidate
from backend.schemas.chat_schema import ChatSource
from backend.services.retrieval_service import RetrievalService


def _chunk(
    *,
    content: str = "body",
    file_name: str = "a.pdf",
    file_path: str = "/a.pdf",
    deleted: bool = False,
):
    document = SimpleNamespace(
        id=uuid4(),
        file_name=file_name,
        file_path=file_path,
        document_type="memo",
        business_domain="ops",
        is_deleted=deleted,
    )
    return SimpleNamespace(
        id=uuid4(),
        content=content,
        section_title="",
        heading_path="",
        page_number=1,
        document=document,
    )


def test_retrieval_candidate_zero_rerank_beats_fused() -> None:
    chunk = _chunk()
    item = RetrievalCandidate(
        chunk=chunk,  # type: ignore[arg-type]
        semantic_score=0.9,
        keyword_score=0.8,
        fused_score=0.7,
        rerank_score=0.0,
    )
    assert item.score == 0.0
    unset = RetrievalCandidate(
        chunk=chunk,  # type: ignore[arg-type]
        semantic_score=0.9,
        fused_score=0.05,
        rerank_score=None,
    )
    assert unset.score == 0.05


def test_rrf_preserves_ranks_and_prefers_multi_channel() -> None:
    a = RetrievalCandidate(chunk=_chunk(content="a"), semantic_score=0.9)  # type: ignore[arg-type]
    b = RetrievalCandidate(chunk=_chunk(content="b"), semantic_score=0.8)  # type: ignore[arg-type]
    c = RetrievalCandidate(chunk=_chunk(content="c"), keyword_score=0.7)  # type: ignore[arg-type]
    # Put b in both lists so RRF should beat single-channel a/c at same depth.
    semantic = [a, b]
    keyword = [
        RetrievalCandidate(chunk=b.chunk, keyword_score=0.95),
        c,
    ]
    merged = merge_candidates_rrf(semantic, keyword)
    by_id = {item.candidate_id: item for item in merged}
    assert by_id[b.candidate_id].semantic_rank == 2
    assert by_id[b.candidate_id].keyword_rank == 1
    assert by_id[b.candidate_id].fused_score > by_id[a.candidate_id].fused_score
    assert by_id[b.candidate_id].rerank_score is None


def test_cross_encoder_normalize_no_minmax_singleton() -> None:
    # Singleton must not become 0.5 via min/max; sigmoid(0)=0.5 only for logit 0.
    assert CrossEncoderReranker._normalize_scores([0.0]) == [0.5]
    tight = CrossEncoderReranker._normalize_scores([-20.0, -19.0])
    assert tight[0] < 0.01
    assert tight[1] < 0.01
    assert tight[1] > tight[0]
    # Relative gap stays tiny — no artificial [0, .999] stretch.
    assert tight[1] - tight[0] < 0.01


def test_select_grounded_abstains_on_hard_negative() -> None:
    service = RetrievalService.__new__(RetrievalService)
    weak = RetrievalCandidate(
        chunk=_chunk(content="unrelated lunch menu"),  # type: ignore[arg-type]
        semantic_score=0.1,
        keyword_score=0.0,
        fused_score=0.02,
        rerank_score=0.12,
    )
    selected = service._select_grounded_chunks(
        ranked_chunks=[weak],
        keyword_terms=["invoice", "1042"],
        top_k=3,
        allow_scoped_fallback=True,
    )
    assert selected == []


def test_select_grounded_keeps_exact_identifier() -> None:
    service = RetrievalService.__new__(RetrievalService)
    hit = RetrievalCandidate(
        chunk=_chunk(
            content="Reference INV-1042 paid.",
            file_name="invoice-inv-1042.pdf",
            file_path="/finance/invoice-inv-1042.pdf",
        ),  # type: ignore[arg-type]
        semantic_score=0.2,
        keyword_score=0.1,
        fused_score=0.03,
        rerank_score=0.2,
    )
    selected = service._select_grounded_chunks(
        ranked_chunks=[hit],
        keyword_terms=["INV-1042"],
        top_k=3,
    )
    assert len(selected) == 1
    assert selected[0][0] is hit.chunk


def test_postprocess_preserves_final_rank_order() -> None:
    sources = [
        ChatSource(
            chunk_id=uuid4(),
            document_id=uuid4(),
            file_name="a.pdf",
            file_path="/a.pdf",
            snippet="alpha",
            distance=0.1,
            score=0.9,
            content="alpha token rare",
        ),
        ChatSource(
            chunk_id=uuid4(),
            document_id=uuid4(),
            file_name="b.pdf",
            file_path="/b.pdf",
            snippet="beta",
            distance=0.2,
            score=0.8,
            content="question word word word",
        ),
        ChatSource(
            chunk_id=uuid4(),
            document_id=uuid4(),
            file_name="c.pdf",
            file_path="/c.pdf",
            snippet="gamma",
            distance=0.3,
            score=0.7,
            content="gamma",
        ),
    ]
    stats: dict[str, object] = {}
    out = rerank_and_truncate_sources(
        "question word", sources, stats_out=stats
    )
    assert [str(item.chunk_id) for item in out] == [
        str(item.chunk_id) for item in sources
    ]
    assert stats.get("lexical_rerank") == "disabled"
    assert stats.get("order_changed") is False
    assert rerank_sources_lexically("question word", sources) == sources
