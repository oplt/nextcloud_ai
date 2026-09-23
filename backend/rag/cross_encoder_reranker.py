from __future__ import annotations

import asyncio
import math
from functools import partial

from .stores import RetrievalCandidate


class CrossEncoderReranker:
    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        max_length: int = 512,
    ) -> None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:  # pragma: no cover - exercised via runtime
            raise ImportError(
                "sentence_transformers is required for true reranking. "
                "Install with: pip/uv install '.[rerank]'"
            ) from exc

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

        # Sigmoid maps logits into (0, 1). Order-preserving; not calibrated
        # abstention — thresholds need held-out negatives.
        mapped = [_logit_to_probability(float(score)) for score in scores]
        if len(mapped) != len(candidates):
            raise ValueError("cross-encoder score count does not match candidate count")

        for candidate, score in zip(candidates, mapped, strict=True):
            candidate.rerank_score = score

        return sorted(
            candidates,
            key=lambda item: (
                item.rerank_score if item.rerank_score is not None else -1.0,
                item.fused_score,
                item.candidate_id,
            ),
            reverse=True,
        )

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
        """Map raw cross-encoder logits with sigmoid. No query-local min/max."""
        return [_logit_to_probability(score) for score in scores]


def _logit_to_probability(logit: float) -> float:
    # Stable sigmoid. Zero logit → 0.5; does not invent relative confidence.
    if logit >= 0:
        return 1.0 / (1.0 + math.exp(-logit))
    exp_x = math.exp(logit)
    return exp_x / (1.0 + exp_x)
