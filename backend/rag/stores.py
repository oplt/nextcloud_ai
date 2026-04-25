from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from ..core.security import AuthContext
from ..db.models import DocumentChunk
from ..db.repo.document import DocumentChunkRepository
from ..schemas.chat_schema import RetrievalFilters
from ..ai.citations import distance_to_score

_TOKEN_RE = re.compile(r"[^\W\s]+", flags=re.UNICODE)


@dataclass(slots=True)
class RetrievalCandidate:
    chunk: DocumentChunk
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    rerank_score: float = 0.0
    fused_score: float = 0.0

    @property
    def score(self) -> float:
        return self.rerank_score or self.fused_score or max(
            self.semantic_score, self.keyword_score
        )

    @property
    def lexical_score(self) -> float:
        return self.keyword_score

    @lexical_score.setter
    def lexical_score(self, value: float) -> None:
        self.keyword_score = value


class PgVectorStore:
    def __init__(self, repo: DocumentChunkRepository) -> None:
        self.repo = repo

    async def search(
        self,
        *,
        embedding: list[float],
        auth: AuthContext,
        limit: int,
        document_ids: Sequence[UUID] | None,
        filters: RetrievalFilters | None,
    ) -> list[RetrievalCandidate]:
        rows = await self.repo.semantic_search(
            embedding=embedding,
            auth=auth,
            limit=limit,
            document_ids=document_ids,
            connector_ids=filters.connector_ids if filters else None,
            mime_types=filters.mime_types if filters else None,
            path_prefixes=filters.path_prefixes if filters else None,
            modified_after=filters.modified_after if filters else None,
            modified_before=filters.modified_before if filters else None,
            document_types=filters.document_types if filters else None,
            business_domains=filters.business_domains if filters else None,
            source_types=filters.source_types if filters else None,
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
        auth: AuthContext,
        limit: int,
        document_ids: Sequence[UUID] | None,
        filters: RetrievalFilters | None,
    ) -> list[RetrievalCandidate]:
        chunks = await self.repo.keyword_search(
            terms=terms,
            auth=auth,
            limit=limit,
            document_ids=document_ids,
            connector_ids=filters.connector_ids if filters else None,
            mime_types=filters.mime_types if filters else None,
            path_prefixes=filters.path_prefixes if filters else None,
            modified_after=filters.modified_after if filters else None,
            modified_before=filters.modified_before if filters else None,
            document_types=filters.document_types if filters else None,
            business_domains=filters.business_domains if filters else None,
            source_types=filters.source_types if filters else None,
        )
        return [
            RetrievalCandidate(chunk=chunk, keyword_score=score)
            for chunk, score in bm25_score_chunks(terms, chunks)
        ]


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text or "") if token.strip()]


def bm25_score_chunks(
    terms: Sequence[str], chunks: Sequence[DocumentChunk]
) -> list[tuple[DocumentChunk, float]]:
    query_terms = [term.lower() for term in terms if term]
    if not query_terms or not chunks:
        return []

    tokenized = [_chunk_tokens(chunk) for chunk in chunks]
    doc_freq: Counter[str] = Counter()
    for tokens in tokenized:
        doc_freq.update(set(tokens))
    avgdl = sum(len(tokens) for tokens in tokenized) / max(len(tokenized), 1)
    k1 = 1.5
    b = 0.75
    raw_scores: list[tuple[DocumentChunk, float]] = []
    total_docs = len(chunks)

    for chunk, tokens in zip(chunks, tokenized):
        freqs = Counter(tokens)
        score = 0.0
        dl = len(tokens) or 1
        for term in query_terms:
            tf = freqs.get(term, 0)
            if tf <= 0:
                continue
            idf = math.log(1 + (total_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            denom = tf + k1 * (1 - b + b * dl / max(avgdl, 1.0))
            score += idf * (tf * (k1 + 1)) / denom
        raw_scores.append((chunk, score))

    best = max((score for _, score in raw_scores), default=0.0)
    if best <= 0:
        return []
    return [(chunk, min(0.999, score / best)) for chunk, score in raw_scores if score > 0]


def _chunk_tokens(chunk: DocumentChunk) -> list[str]:
    document = chunk.document
    parts = [
        chunk.content or "",
        chunk.section_title or "",
        chunk.heading_path or "",
        document.file_name if document is not None else "",
        document.file_path if document is not None else "",
    ]
    return tokenize(" ".join(parts))
