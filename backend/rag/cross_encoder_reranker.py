from __future__ import annotations

import asyncio
from functools import partial

from sentence_transformers import CrossEncoder

from .stores import RetrievalCandidate


class CrossEncoderReranker:
    def __init__(
            self,
            *,
            model_name: str = "BAAI/bge-reranker-v2-m3",
            max_length: int = 512,
    ) -> None:
        self.model_name = model_name
        self.model = CrossEncoder(model_name, max_length=max_length)

    async def rerank(
            self,
            *,
            question: str,
            candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        if not candidates:
            return []

        pairs = [
            (
                question,
                self._candidate_text(candidate),
            )
            for candidate in candidates
        ]

        scores = await asyncio.to_thread(
            partial(
                self.model.predict,
                pairs,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        )

        normalized_scores = self._normalize_scores([float(score) for score in scores])

        for candidate, score in zip(candidates, normalized_scores):
            candidate.rerank_score = score

        return sorted(candidates, key=lambda item: item.rerank_score, reverse=True)

    @staticmethod
    def _candidate_text(candidate: RetrievalCandidate) -> str:
        chunk = candidate.chunk
        document = chunk.document

        parts = [
            document.file_name if document is not None else "",
            document.file_path if document is not None else "",
            chunk.section_title or "",
            chunk.heading_path or "",
            chunk.content or "",
            ]

        return "\n".join(part for part in parts if part).strip()

    @staticmethod
    def _normalize_scores(scores: list[float]) -> list[float]:
        if not scores:
            return []

        low = min(scores)
        high = max(scores)

        if high == low:
            return [0.5 for _ in scores]

        return [
            max(0.0, min(0.999, (score - low) / (high - low)))
            for score in scores
        ]