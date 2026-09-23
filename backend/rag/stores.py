from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..ai.citations import distance_to_score
from ..ai.embedding_contract import active_embedding_fingerprint
from ..core.security import AuthContext
from ..db.models import DocumentChunk
from ..db.repo.document import DocumentChunkRepository
from ..schemas.chat_schema import RetrievalFilters
from .lexical import chunk_overlap_score, semantic_json_text, squash_ts_rank, tokenize
from .scope import RetrievalScope


def retrieval_filter_kwargs(filters: RetrievalFilters | None) -> dict:
    """Compatibility helper; active retrieval uses ``RetrievalScope``."""
    anonymous = AuthContext(
        user_id="retrieval-filter-compat", auth_provider="local", is_superuser=False
    )
    return RetrievalScope.resolve(auth=anonymous, filters=filters).repository_filters()


@dataclass(slots=True)
class RetrievalCandidate:
    chunk: DocumentChunk
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    fused_score: float = 0.0
    # None = not scored by the final ranker. Zero is a real (rejected) score.
    rerank_score: float | None = None
    semantic_rank: int | None = None
    keyword_rank: int | None = None

    @property
    def score(self) -> float:
        if self.rerank_score is not None:
            return self.rerank_score
        if self.fused_score > 0:
            return self.fused_score
        return max(self.semantic_score, self.keyword_score)

    @property
    def lexical_score(self) -> float:
        return self.keyword_score

    @lexical_score.setter
    def lexical_score(self, value: float) -> None:
        self.keyword_score = value

    @property
    def candidate_id(self) -> str:
        return str(self.chunk.id)


class PgVectorStore:
    def __init__(self, repo: DocumentChunkRepository) -> None:
        self.repo = repo

    async def search(
        self,
        *,
        embedding: list[float],
        scope: RetrievalScope,
        limit: int,
    ) -> list[RetrievalCandidate]:
        rows = await self.repo.semantic_search(
            embedding=embedding,
            auth=scope.auth,
            limit=limit,
            document_ids=scope.document_ids,
            embedding_fingerprint=active_embedding_fingerprint().digest(),
            **scope.repository_filters(),
        )
        return [
            RetrievalCandidate(chunk=chunk, semantic_score=distance_to_score(distance))
            for chunk, distance in rows
        ]


class KeywordSearchStore:
    def __init__(self, repo: DocumentChunkRepository) -> None:
        self.repo = repo

    async def search(
        self,
        *,
        terms: Sequence[str],
        scope: RetrievalScope,
        limit: int,
    ) -> list[RetrievalCandidate]:
        rows = await self.repo.keyword_search(
            terms=terms,
            auth=scope.auth,
            limit=limit,
            document_ids=scope.document_ids,
            **scope.repository_filters(),
        )
        return [
            RetrievalCandidate(
                chunk=chunk,
                keyword_score=squash_ts_rank(rank),
            )
            for chunk, rank in rows
            if rank > 0
        ]


def bm25_score_chunks(
    terms: Sequence[str], chunks: Sequence[DocumentChunk]
) -> list[tuple[DocumentChunk, float]]:
    """Local term coverage on allowlisted fields. Not corpus BM25.

    Retrieval rank comes from SQL ``ts_rank_cd``. This helper is for tests and
    offline overlap only — IDF over the candidate window is intentionally gone.
    """
    scored: list[tuple[DocumentChunk, float]] = []
    for chunk in chunks:
        score = chunk_overlap_score(terms, " ".join(_chunk_lexical_parts(chunk)))
        if score > 0:
            scored.append((chunk, score))
    return scored


def _chunk_tokens(chunk: DocumentChunk) -> list[str]:
    return tokenize(" ".join(_chunk_lexical_parts(chunk)))


def _chunk_lexical_parts(chunk: DocumentChunk) -> list[str]:
    document = chunk.document
    return [
        chunk.content or "",
        chunk.section_title or "",
        chunk.heading_path or "",
        document.file_name if document is not None else "",
        document.file_path if document is not None else "",
        document.document_type if document is not None else "",
        document.business_domain if document is not None else "",
        semantic_json_text(document.metadata_json) if document is not None else "",
        semantic_json_text(document.extracted_fields_json)
        if document is not None
        else "",
    ]
