from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from ..core.config import settings
from ..core.security import AuthContext
from ..db.repo.document import DocumentChunkRepository
from ..schemas.chat_schema import RetrievalFilters
from .reranker import ContextReranker
from .stores import KeywordSearchStore, PgVectorStore, RetrievalCandidate

# Standard RRF constant. Higher k → flatter contribution from deep ranks.
_RRF_K = 60


@dataclass(slots=True)
class HybridRetrievalDebug:
    vector_top_k: int = 0
    keyword_top_k: int = 0
    rerank_top_k: int = 0
    final_top_n: int = 0
    semantic_candidates: int = 0
    keyword_candidates: int = 0
    merged_candidates: int = 0
    candidate_window: int = 0
    reranked_candidates: int = 0
    returned_candidates: int = 0
    true_rerank_applied: int = 0
    true_rerank_fallback: str = "none"
    fusion: str = "rrf"

    def as_dict(self) -> dict[str, int | str]:
        return {
            "vector_top_k": self.vector_top_k,
            "keyword_top_k": self.keyword_top_k,
            "rerank_top_k": self.rerank_top_k,
            "final_top_n": self.final_top_n,
            "semantic_candidates": self.semantic_candidates,
            "keyword_candidates": self.keyword_candidates,
            "merged_candidates": self.merged_candidates,
            "candidate_window": self.candidate_window,
            "reranked_candidates": self.reranked_candidates,
            "returned_candidates": self.returned_candidates,
            "true_rerank_applied": self.true_rerank_applied,
            "true_rerank_fallback": self.true_rerank_fallback,
            "fusion": self.fusion,
        }


class HybridRetriever:
    def __init__(self, repo: DocumentChunkRepository) -> None:
        self.vector_store = PgVectorStore(repo)
        self.keyword_store = KeywordSearchStore(repo)
        self.reranker = ContextReranker()

    async def retrieve(
        self,
        *,
        question: str,
        query_embedding: list[float],
        keyword_terms: list[str],
        auth: AuthContext,
        vector_top_k: int | None = None,
        keyword_top_k: int | None = None,
        rerank_top_k: int | None = None,
        final_top_n: int | None = None,
        document_ids: Sequence[UUID] | None,
        filters: RetrievalFilters | None,
    ) -> tuple[list[RetrievalCandidate], HybridRetrievalDebug]:
        vector_limit = vector_top_k or settings.RAG_VECTOR_TOP_K
        keyword_limit = keyword_top_k or settings.RAG_KEYWORD_TOP_K
        rerank_limit = rerank_top_k or settings.RAG_RERANK_TOP_K
        final_limit = final_top_n or settings.RAG_FINAL_TOP_N
        semantic = await self.vector_store.search(
            embedding=query_embedding,
            auth=auth,
            limit=vector_limit,
            document_ids=document_ids,
            filters=filters,
        )
        keyword = await self.keyword_store.search(
            terms=keyword_terms,
            auth=auth,
            limit=keyword_limit,
            document_ids=document_ids,
            filters=filters,
        )
        merged = merge_candidates_rrf(semantic, keyword)
        merged_count = len(merged)
        candidate_window = min(max(rerank_limit, 1), merged_count)
        window = sorted(
            merged,
            key=lambda item: (
                item.fused_score,
                item.semantic_score,
                item.keyword_score,
                item.candidate_id,
            ),
            reverse=True,
        )[:candidate_window]

        reranked, true_applied, true_fallback = await self._finalize_ranking(
            question=question,
            keyword_terms=keyword_terms,
            candidates=window,
        )

        returned = reranked[:final_limit]
        return returned, HybridRetrievalDebug(
            vector_top_k=vector_limit,
            keyword_top_k=keyword_limit,
            rerank_top_k=rerank_limit,
            final_top_n=final_limit,
            semantic_candidates=len(semantic),
            keyword_candidates=len(keyword),
            merged_candidates=merged_count,
            candidate_window=candidate_window,
            reranked_candidates=len(reranked),
            returned_candidates=len(returned),
            true_rerank_applied=true_applied,
            true_rerank_fallback=true_fallback,
            fusion="rrf",
        )

    async def _finalize_ranking(
        self,
        *,
        question: str,
        keyword_terms: list[str],
        candidates: list[RetrievalCandidate],
    ) -> tuple[list[RetrievalCandidate], int, str]:
        """One scoring contract for the chosen window.

        True cross-encoder scores the whole window. Heuristic is a separate,
        observable fallback — never mixed as if scores were comparable.
        """
        if not candidates:
            return candidates, 0, "none"

        if settings.RAG_TRUE_RERANK_ENABLED:
            from .rerank_runtime import get_shared_reranker, get_rerank_status

            true_reranker = get_shared_reranker()
            status = get_rerank_status()
            if true_reranker is not None:
                window = min(len(candidates), max(1, settings.RAG_TRUE_RERANK_TOP_K))
                # Drop unscored tail — those scores are not comparable.
                to_score = candidates[:window]
                reranked = await true_reranker.rerank(
                    question=question,
                    candidates=to_score,
                )
                return reranked, len(reranked), "none"
            fallback = "heuristic" if status.using_fallback else "unavailable"
            if fallback == "unavailable" and settings.RAG_TRUE_RERANK_FALLBACK != "heuristic":
                return [], 0, fallback
        else:
            fallback = "disabled"

        heuristic = self.reranker.rerank(
            question=question,
            keyword_terms=keyword_terms,
            candidates=candidates,
        )
        return heuristic, 0, fallback if settings.RAG_TRUE_RERANK_ENABLED else "disabled"


def merge_candidates_rrf(
    semantic: list[RetrievalCandidate],
    keyword: list[RetrievalCandidate],
    *,
    k: int = _RRF_K,
) -> list[RetrievalCandidate]:
    """Rank-based fusion. Preserves raw channel scores and 1-based ranks."""
    merged: dict[str, RetrievalCandidate] = {}

    for rank, candidate in enumerate(semantic, start=1):
        key = candidate.candidate_id
        entry = RetrievalCandidate(
            chunk=candidate.chunk,
            semantic_score=candidate.semantic_score,
            keyword_score=0.0,
            semantic_rank=rank,
        )
        merged[key] = entry

    for rank, candidate in enumerate(keyword, start=1):
        key = candidate.candidate_id
        existing = merged.get(key)
        if existing is None:
            merged[key] = RetrievalCandidate(
                chunk=candidate.chunk,
                semantic_score=0.0,
                keyword_score=candidate.keyword_score,
                keyword_rank=rank,
            )
            continue
        existing.keyword_score = max(existing.keyword_score, candidate.keyword_score)
        existing.keyword_rank = rank
        existing.semantic_score = max(existing.semantic_score, candidate.semantic_score)

    for entry in merged.values():
        fused = 0.0
        if entry.semantic_rank is not None:
            fused += 1.0 / (k + entry.semantic_rank)
        if entry.keyword_rank is not None:
            fused += 1.0 / (k + entry.keyword_rank)
        entry.fused_score = fused
        entry.rerank_score = None

    return list(merged.values())


# Back-compat alias used by older call sites / tests.
_merge_candidates = merge_candidates_rrf
