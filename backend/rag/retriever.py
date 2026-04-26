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

    def as_dict(self) -> dict[str, int]:
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
        }


class HybridRetriever:
    def __init__(self, repo: DocumentChunkRepository) -> None:
        self.vector_store = PgVectorStore(repo)
        self.keyword_store = KeywordSearchStore(repo)
        self.reranker = ContextReranker()
        self.true_reranker = None

    def _get_true_reranker(self):
        if self.true_reranker is None:
            from .cross_encoder_reranker import CrossEncoderReranker

            self.true_reranker = CrossEncoderReranker(
                model_name=settings.RAG_TRUE_RERANK_MODEL,
            )

        return self.true_reranker

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
        merged = _merge_candidates(semantic, keyword)
        merged_count = len(merged)
        candidate_window = min(max(rerank_limit, 1), merged_count)
        merged = sorted(
            merged,
            key=lambda item: (
                item.semantic_score * 0.7 + item.keyword_score * 0.3,
                item.semantic_score,
                item.keyword_score,
            ),
            reverse=True,
        )[:candidate_window]
        heuristic_reranked = self.reranker.rerank(
            question=question,
            keyword_terms=keyword_terms,
            candidates=merged,
        )

        reranked = await self._maybe_true_rerank(
            question=question,
            candidates=heuristic_reranked,
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
        )

    async def _maybe_true_rerank(self, *, question: str, candidates:list[RetrievalCandidate],) -> list[RetrievalCandidate]:
        if not settings.RAG_TRUE_RERANK_ENABLED:
            return candidates

        if not candidates:
            return candidates

        from .cross_encoder_reranker import CrossEncoderReranker

        window = max(1, settings.RAG_TRUE_RERANK_TOP_K)
        head = candidates[:window]
        tail = candidates[window:]

        true_reranker = self._get_true_reranker()

        reranked_head = await true_reranker.rerank(
            question=question,
            candidates=head,
        )

        return [*reranked_head, *tail]


def _merge_candidates(
    semantic: list[RetrievalCandidate], keyword: list[RetrievalCandidate]
) -> list[RetrievalCandidate]:
    merged: dict[str, RetrievalCandidate] = {}
    for candidate in [*semantic, *keyword]:
        key = str(candidate.chunk.id)
        existing = merged.get(key)
        if existing is None:
            merged[key] = candidate
            continue
        existing.semantic_score = max(existing.semantic_score, candidate.semantic_score)
        existing.keyword_score = max(existing.keyword_score, candidate.keyword_score)
    return list(merged.values())
