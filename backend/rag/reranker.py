from __future__ import annotations

from ..db.models import DocumentChunk
from .stores import RetrievalCandidate


class ContextReranker:
    def __init__(self, *, vector_weight: float = 0.3, metadata_weight: float = 0.08) -> None:
        self.vector_weight = max(0.0, min(1.0, vector_weight))
        self.keyword_weight = 1.0 - self.vector_weight
        self.metadata_weight = max(0.0, min(0.2, metadata_weight))

    def rerank(
        self,
        *,
        question: str,
        keyword_terms: list[str],
        candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        del question
        for candidate in candidates:
            candidate.fused_score = self._weighted_fusion(candidate)
            candidate.rerank_score = self._score(
                keyword_terms=keyword_terms,
                candidate=candidate,
            )
        return sorted(candidates, key=lambda item: item.score, reverse=True)

    def _score(
        self,
        *,
        keyword_terms: list[str],
        candidate: RetrievalCandidate,
    ) -> float:
        chunk = candidate.chunk
        base = (
            self._weighted_fusion(candidate) * (1.0 - self.metadata_weight)
            + self._metadata_score(keyword_terms, chunk) * self.metadata_weight
        )
        return min(0.999, max(0.0, base))

    def _weighted_fusion(self, candidate: RetrievalCandidate) -> float:
        return min(
            0.999,
            max(
                0.0,
                candidate.semantic_score * self.vector_weight
                + candidate.keyword_score * self.keyword_weight,
            ),
        )

    @staticmethod
    def _metadata_score(keyword_terms: list[str], chunk: DocumentChunk) -> float:
        if not keyword_terms:
            return 0.0
        document = chunk.document
        haystack = " ".join(
            [
                chunk.section_title or "",
                chunk.heading_path or "",
                document.file_name if document is not None else "",
                document.file_path if document is not None else "",
            ]
        ).lower()
        if not haystack:
            return 0.0
        hits = sum(1 for term in keyword_terms if term in haystack)
        return hits / max(len(keyword_terms), 1)
