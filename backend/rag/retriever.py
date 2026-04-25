from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from ..core.security import AuthContext
from ..db.repo.document import DocumentChunkRepository
from ..schemas.chat_schema import RetrievalFilters
from .reranker import ContextReranker
from .stores import KeywordSearchStore, PgVectorStore, RetrievalCandidate


@dataclass(slots=True)
class HybridRetrievalDebug:
    semantic_candidates: int = 0
    keyword_candidates: int = 0
    merged_candidates: int = 0
    candidate_window: int = 0
    reranked_candidates: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "semantic_candidates": self.semantic_candidates,
            "keyword_candidates": self.keyword_candidates,
            "merged_candidates": self.merged_candidates,
            "candidate_window": self.candidate_window,
            "reranked_candidates": self.reranked_candidates,
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
        limit: int,
        document_ids: Sequence[UUID] | None,
        filters: RetrievalFilters | None,
    ) -> tuple[list[RetrievalCandidate], HybridRetrievalDebug]:
        semantic = await self.vector_store.search(
            embedding=query_embedding,
            auth=auth,
            limit=limit,
            document_ids=document_ids,
            filters=filters,
        )
        keyword = await self.keyword_store.search(
            terms=keyword_terms,
            auth=auth,
            limit=limit,
            document_ids=document_ids,
            filters=filters,
        )
        merged = _merge_candidates(semantic, keyword)
        candidate_window = min(max(limit, 1), 64)
        merged = sorted(
            merged,
            key=lambda item: (
                item.semantic_score * 0.7 + item.keyword_score * 0.3,
                item.semantic_score,
                item.keyword_score,
            ),
            reverse=True,
        )[:candidate_window]
        reranked = self.reranker.rerank(
            question=question,
            keyword_terms=keyword_terms,
            candidates=merged,
        )
        return reranked, HybridRetrievalDebug(
            semantic_candidates=len(semantic),
            keyword_candidates=len(keyword),
            merged_candidates=len(merged),
            candidate_window=candidate_window,
            reranked_candidates=len(reranked),
        )


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
