from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.citations import build_snippet, distance_to_score
from backend.ai.embedding_client import EmbeddingClientFactory, EmbeddingClientProtocol
from backend.core.security import AuthContext
from backend.db.models import DocumentChunk
from backend.db.repo.document import DocumentChunkRepository
from backend.schemas.chat_schema import ChatSource

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "between",
    "by",
    "did",
    "do",
    "does",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "where",
    "who",
    "with",
    "work",
    "worked",
}


@dataclass(slots=True)
class RetrievalResult:
    sources: list[ChatSource]
    query_embedding: list[float]


@dataclass(slots=True)
class RankedChunk:
    chunk: DocumentChunk
    semantic_score: float = 0.0
    lexical_score: float = 0.0

    @property
    def score(self) -> float:
        if self.semantic_score and self.lexical_score:
            return min(
                0.999,
                max(self.semantic_score, self.lexical_score)
                + min(self.semantic_score, self.lexical_score) * 0.15,
            )
        return max(self.semantic_score, self.lexical_score)


class RetrievalService:
    def __init__(
        self,
        session: AsyncSession,
        embedding_client: EmbeddingClientProtocol | None = None,
    ) -> None:
        self.session = session
        self.embedding_client = embedding_client or EmbeddingClientFactory.create()
        self.chunk_repo = DocumentChunkRepository(session)

    async def retrieve(
        self,
        *,
        question: str,
        auth: AuthContext,
        top_k: int = 6,
        document_ids: list[UUID] | None = None,
    ) -> RetrievalResult:
        query_embedding = await self.embedding_client.embed_query(question)
        candidate_limit = max(top_k * 4, 12)
        semantic_rows = await self.chunk_repo.semantic_search(
            embedding=query_embedding,
            auth=auth,
            limit=candidate_limit,
            document_ids=document_ids,
        )
        keyword_terms = self._extract_keyword_terms(question)
        keyword_chunks = await self.chunk_repo.keyword_search(
            terms=keyword_terms,
            auth=auth,
            limit=candidate_limit,
            document_ids=document_ids,
        )

        ranked_chunks = self._merge_ranked_chunks(
            keyword_terms=keyword_terms,
            semantic_rows=semantic_rows,
            keyword_chunks=keyword_chunks,
        )
        diversified_chunks = self._select_distinct_documents(
            ranked_chunks=ranked_chunks,
            keyword_terms=keyword_terms,
            top_k=top_k,
        )

        sources: list[ChatSource] = []
        for chunk, score in diversified_chunks:
            document = chunk.document
            if document is None or document.is_deleted:
                continue
            sources.append(
                ChatSource(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    file_name=document.file_name,
                    file_path=document.file_path,
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    snippet=build_snippet(chunk.content),
                    distance=max(0.0, 1.0 - score),
                    score=score,
                )
            )
        return RetrievalResult(sources=sources, query_embedding=query_embedding)

    @staticmethod
    def _extract_keyword_terms(question: str) -> list[str]:
        tokens = [
            token
            for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]*", question.lower())
            if (len(token) >= 3 or token.isdigit()) and token not in _STOPWORDS
        ]
        terms: list[str] = []
        seen: set[str] = set()
        for term in tokens:
            if term in seen:
                continue
            seen.add(term)
            terms.append(term)
        return terms

    def _merge_ranked_chunks(
        self,
        *,
        keyword_terms: list[str],
        semantic_rows: list[tuple[DocumentChunk, float]],
        keyword_chunks: list[DocumentChunk],
    ) -> list[RankedChunk]:
        merged: dict[str, RankedChunk] = {}

        for chunk, distance in semantic_rows:
            merged[str(chunk.id)] = RankedChunk(
                chunk=chunk,
                semantic_score=distance_to_score(distance),
            )

        for chunk in keyword_chunks:
            lexical_score = self._keyword_score(keyword_terms, chunk)
            existing = merged.get(str(chunk.id))
            if existing is None:
                merged[str(chunk.id)] = RankedChunk(
                    chunk=chunk,
                    lexical_score=lexical_score,
                )
                continue
            existing.lexical_score = max(existing.lexical_score, lexical_score)

        return sorted(merged.values(), key=lambda item: item.score, reverse=True)

    def _select_distinct_documents(
        self,
        *,
        ranked_chunks: list[RankedChunk],
        keyword_terms: list[str],
        top_k: int,
    ) -> list[tuple[DocumentChunk, float]]:
        if not ranked_chunks:
            return []

        has_lexical_hits = any(item.lexical_score > 0 for item in ranked_chunks)
        best_score = ranked_chunks[0].score
        min_score = max(0.35, best_score * 0.55)
        selected: list[tuple[DocumentChunk, float]] = []
        seen_documents: set[str] = set()

        for item in ranked_chunks:
            chunk = item.chunk
            document = chunk.document
            if document is None or document.is_deleted:
                continue
            document_key = str(document.id)
            if document_key in seen_documents:
                continue

            # When exact lexical hits exist, suppress semantic-only documents unless
            # they are exceptionally strong matches. This avoids stray unrelated files.
            if has_lexical_hits and keyword_terms and item.lexical_score == 0 and item.score < 0.98:
                continue
            if item.score < min_score:
                continue

            selected.append((chunk, item.score))
            seen_documents.add(document_key)
            if len(selected) >= top_k:
                break

        if selected:
            return selected

        fallback_selected: list[tuple[DocumentChunk, float]] = []
        for item in ranked_chunks:
            chunk = item.chunk
            document = chunk.document
            if document is None or document.is_deleted:
                continue
            document_key = str(document.id)
            if document_key in seen_documents:
                continue
            fallback_selected.append((chunk, item.score))
            seen_documents.add(document_key)
            if len(fallback_selected) >= top_k:
                break
        return fallback_selected

    def _keyword_score(self, keyword_terms: list[str], chunk: DocumentChunk) -> float:
        document = chunk.document
        haystack = " ".join(
            part.lower()
            for part in [
                document.file_name if document else "",
                document.file_path if document else "",
                chunk.section_title or "",
                chunk.content,
            ]
            if part
        )
        if not haystack:
            return 0.0

        terms = keyword_terms
        if not terms:
            return 0.0

        token_matches = sum(1 for term in terms if term in haystack)
        phrase_matches = sum(
            1
            for left, right in zip(terms, terms[1:])
            if f"{left} {right}" in haystack
        )
        coverage = token_matches / max(len(terms), 1)
        phrase_bonus = 0.25 * (phrase_matches / max(len(terms) - 1, 1))
        score = coverage + phrase_bonus
        if token_matches >= 2 and phrase_matches >= 1:
            score += 0.15
        if any(term.isdigit() and term in haystack for term in terms):
            score += 0.05
        return min(0.999, max(0.0, score))
