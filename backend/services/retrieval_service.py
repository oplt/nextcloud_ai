from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.citations import build_snippet, distance_to_score
from backend.ai.embedding_client import EmbeddingClientFactory, EmbeddingClientProtocol
from backend.core.security import AuthContext
from backend.db.models import DocumentChunk
from backend.db.repo.document import DocumentChunkRepository
from backend.schemas.chat_schema import ChatSource

_STOPWORDS = {
    'a', 'an', 'and', 'are', 'between', 'by', 'did', 'do', 'does', 'for', 'from',
    'in', 'is', 'of', 'on', 'or', 'the', 'to', 'was', 'where', 'who', 'with', 'work', 'worked',
}
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_YEAR_RANGE_RE = re.compile(
    r"\b(?:[A-Za-z]{3,9}\s+)?(?P<start>(?:19|20)\d{2})\b"
    r"\s*(?:-|–|—|to|through|until)\s*"
    r"(?:(?:[A-Za-z]{3,9}\s+)?(?P<end>(?:19|20)\d{2})|(?P<open>present|current|now))",
    flags=re.IGNORECASE,
)
_EMPLOYMENT_HINT_RE = re.compile(
    r"\b(?:work experience|employment history|worked|employed|employment|job|role|position|"
    r"developer|engineer|analyst|researcher|manager|officer|consultant|specialist|intern)\b",
    flags=re.IGNORECASE,
)
_EDUCATION_HINT_RE = re.compile(
    r"\b(?:education|qualifications|qualification|phd|master(?:'s)?|bachelor(?:'s)?|student|"
    r"thesis|degree|diploma)\b",
    flags=re.IGNORECASE,
)

_ABSOLUTE_MIN_SCORE = 0.40
_NARROW_CONFIDENCE_THRESHOLD = 0.58
_MAX_CHUNKS_PER_DOCUMENT = 2
_MAX_CONTEXTUAL_CHUNKS_PER_DOCUMENT = 4


@dataclass(slots=True)
class RetrievalResult:
    sources: list[ChatSource]
    query_embedding: list[float]
    grounded_document_ids: list[UUID] = field(default_factory=list)


@dataclass(slots=True)
class RankedChunk:
    chunk: DocumentChunk
    semantic_score: float = 0.0
    lexical_score: float = 0.0
    contextual_score: float = 0.0

    @property
    def score(self) -> float:
        base_score: float
        if self.semantic_score and self.lexical_score:
            base_score = max(self.semantic_score, self.lexical_score) + min(
                self.semantic_score, self.lexical_score
            ) * 0.15
        else:
            base_score = max(self.semantic_score, self.lexical_score)
        return min(0.999, max(0.0, base_score + self.contextual_score))


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
        preferred_document_ids: list[UUID] | None = None,
    ) -> RetrievalResult:
        query_embedding = await self.embedding_client.embed_query(question)
        keyword_terms = self._extract_keyword_terms(question)
        allow_contextual_tail = self._looks_like_relative_employment_question(question)

        if preferred_document_ids:
            narrow_result = await self._run_retrieval(
                question=question,
                query_embedding=query_embedding,
                keyword_terms=keyword_terms,
                auth=auth,
                top_k=top_k,
                document_ids=preferred_document_ids,
                allow_semantic_context_chunks=allow_contextual_tail,
                max_chunks_per_document=(
                    _MAX_CONTEXTUAL_CHUNKS_PER_DOCUMENT
                    if allow_contextual_tail
                    else _MAX_CHUNKS_PER_DOCUMENT
                ),
            )
            if narrow_result and narrow_result[0][1] >= _NARROW_CONFIDENCE_THRESHOLD:
                return self._build_result(narrow_result, query_embedding)

        broad_result = await self._run_retrieval(
            question=question,
            query_embedding=query_embedding,
            keyword_terms=keyword_terms,
            auth=auth,
            top_k=top_k,
            document_ids=document_ids,
            allow_semantic_context_chunks=allow_contextual_tail and bool(document_ids),
            max_chunks_per_document=(
                _MAX_CONTEXTUAL_CHUNKS_PER_DOCUMENT
                if allow_contextual_tail and document_ids
                else _MAX_CHUNKS_PER_DOCUMENT
            ),
        )
        return self._build_result(broad_result, query_embedding)

    async def _run_retrieval(
        self,
        *,
        question: str,
        query_embedding: list[float],
        keyword_terms: list[str],
        auth: AuthContext,
        top_k: int,
        document_ids: list[UUID] | None,
        allow_semantic_context_chunks: bool = False,
        max_chunks_per_document: int = _MAX_CHUNKS_PER_DOCUMENT,
    ) -> list[tuple[DocumentChunk, float]]:
        candidate_limit = max(top_k * 6, 18)

        semantic_rows = await self.chunk_repo.semantic_search(
            embedding=query_embedding,
            auth=auth,
            limit=candidate_limit,
            document_ids=document_ids,
        )
        keyword_chunks = await self.chunk_repo.keyword_search(
            terms=keyword_terms,
            auth=auth,
            limit=candidate_limit,
            document_ids=document_ids,
        )

        ranked_chunks = self._merge_ranked_chunks(
            question=question,
            keyword_terms=keyword_terms,
            semantic_rows=semantic_rows,
            keyword_chunks=keyword_chunks,
        )
        return self._select_grounded_chunks(
            ranked_chunks=ranked_chunks,
            keyword_terms=keyword_terms,
            top_k=top_k,
            allow_semantic_context_chunks=allow_semantic_context_chunks,
            max_chunks_per_document=max_chunks_per_document,
        )

    @staticmethod
    def _build_result(
        grounded_chunks: list[tuple[DocumentChunk, float]],
        query_embedding: list[float],
    ) -> RetrievalResult:
        sources: list[ChatSource] = []
        grounded_ids: list[UUID] = []
        seen_doc_ids: set[str] = set()

        for chunk, score in grounded_chunks:
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
                    snippet=build_snippet(chunk.content, limit=420),
                    distance=max(0.0, 1.0 - score),
                    score=score,
                    content=chunk.content,
                )
            )
            document_key = str(document.id)
            if document_key not in seen_doc_ids:
                seen_doc_ids.add(document_key)
                grounded_ids.append(document.id)

        return RetrievalResult(
            sources=sources,
            query_embedding=query_embedding,
            grounded_document_ids=grounded_ids,
        )

    @staticmethod
    def _extract_keyword_terms(question: str) -> list[str]:
        tokens = [
            token
            for token in re.findall(r'[A-Za-z0-9][A-Za-z0-9._/-]*', question.lower())
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
        question: str,
        keyword_terms: list[str],
        semantic_rows: list[tuple[DocumentChunk, float]],
        keyword_chunks: list[DocumentChunk],
    ) -> list[RankedChunk]:
        merged: dict[str, RankedChunk] = {}
        question_years = self._extract_question_years(question)
        employment_question = self._looks_like_employment_question(question)

        for chunk, distance in semantic_rows:
            merged[str(chunk.id)] = RankedChunk(
                chunk=chunk,
                semantic_score=distance_to_score(distance),
                contextual_score=self._contextual_score(
                    chunk=chunk,
                    years=question_years,
                    employment_question=employment_question,
                ),
            )

        for chunk in keyword_chunks:
            lexical_score = self._keyword_score(keyword_terms, chunk)
            existing = merged.get(str(chunk.id))
            if existing is None:
                merged[str(chunk.id)] = RankedChunk(
                    chunk=chunk,
                    lexical_score=lexical_score,
                    contextual_score=self._contextual_score(
                        chunk=chunk,
                        years=question_years,
                        employment_question=employment_question,
                    ),
                )
                continue
            existing.lexical_score = max(existing.lexical_score, lexical_score)

        return sorted(merged.values(), key=lambda item: item.score, reverse=True)

    def _select_grounded_chunks(
        self,
        *,
        ranked_chunks: list[RankedChunk],
        keyword_terms: list[str],
        top_k: int,
        allow_semantic_context_chunks: bool = False,
        max_chunks_per_document: int = _MAX_CHUNKS_PER_DOCUMENT,
    ) -> list[tuple[DocumentChunk, float]]:
        if not ranked_chunks:
            return []

        has_lexical_hits = any(item.lexical_score > 0 for item in ranked_chunks)
        best_score = ranked_chunks[0].score
        min_score = max(_ABSOLUTE_MIN_SCORE, best_score * 0.55)

        selected: list[tuple[DocumentChunk, float]] = []
        selected_chunk_ids: set[str] = set()
        doc_counts: dict[str, int] = {}

        for item in ranked_chunks:
            chunk = item.chunk
            document = chunk.document
            if document is None or document.is_deleted:
                continue
            if item.score < _ABSOLUTE_MIN_SCORE or item.score < min_score:
                continue
            if (
                has_lexical_hits
                and keyword_terms
                and item.lexical_score == 0
                and item.score < 0.98
                and not allow_semantic_context_chunks
            ):
                continue

            document_key = str(document.id)
            current_doc_count = doc_counts.get(document_key, 0)
            if current_doc_count >= max_chunks_per_document:
                continue

            if current_doc_count == 0 and selected and not self._is_additional_document_match(item=item, best_score=best_score):
                continue

            selected.append((chunk, item.score))
            selected_chunk_ids.add(str(chunk.id))
            doc_counts[document_key] = current_doc_count + 1
            if len(selected) >= top_k:
                break

        if allow_semantic_context_chunks and selected and len(selected) < top_k:
            seeded_document_ids = {
                str(chunk.document.id)
                for chunk, _ in selected
                if chunk.document is not None
            }
            for item in ranked_chunks:
                chunk = item.chunk
                document = chunk.document
                if document is None or document.is_deleted:
                    continue
                if item.score < _ABSOLUTE_MIN_SCORE:
                    continue

                document_key = str(document.id)
                if document_key not in seeded_document_ids:
                    continue
                if str(chunk.id) in selected_chunk_ids:
                    continue

                current_doc_count = doc_counts.get(document_key, 0)
                if current_doc_count >= max_chunks_per_document:
                    continue

                selected.append((chunk, item.score))
                selected_chunk_ids.add(str(chunk.id))
                doc_counts[document_key] = current_doc_count + 1
                if len(selected) >= top_k:
                    break

        if selected:
            return selected

        for item in ranked_chunks:
            chunk = item.chunk
            document = chunk.document
            if document is None or document.is_deleted:
                continue
            if item.score < _ABSOLUTE_MIN_SCORE:
                break
            return [(chunk, item.score)]

        return []

    @staticmethod
    def _is_additional_document_match(*, item: RankedChunk, best_score: float) -> bool:
        if item.score >= max(0.94, best_score - 0.03):
            return True
        if item.lexical_score >= 0.5:
            return True
        return item.score >= max(best_score - 0.06, min(0.74, best_score))

    @staticmethod
    def _extract_question_years(question: str) -> list[str]:
        return list(dict.fromkeys(_YEAR_RE.findall(question)))

    @staticmethod
    def _extract_year_ranges(text: str) -> list[tuple[int, int]]:
        ranges: list[tuple[int, int]] = []
        for match in _YEAR_RANGE_RE.finditer(text):
            start_year = int(match.group('start'))
            end_year = int(match.group('end')) if match.group('end') else start_year
            if end_year < start_year:
                start_year, end_year = end_year, start_year
            ranges.append((start_year, end_year))
        return ranges

    @classmethod
    def _text_supports_year(cls, text: str, year: str) -> bool:
        if re.search(rf"\b{re.escape(str(year))}\b", text):
            return True
        year_value = int(year)
        return any(start_year <= year_value <= end_year for start_year, end_year in cls._extract_year_ranges(text))

    @staticmethod
    def _looks_like_employment_question(question: str) -> bool:
        lowered = f" {question.lower()} "
        return any(
            term in lowered
            for term in (' work ', ' worked ', ' employer ', ' employed ', ' employment ', ' job ', ' role ', ' position ')
        )

    @classmethod
    def _looks_like_relative_employment_question(cls, question: str) -> bool:
        if not cls._looks_like_employment_question(question):
            return False
        lowered = f" {question.lower()} "
        return any(
            marker in lowered
            for marker in (
                ' after ',
                ' before ',
                ' next ',
                ' previous ',
                ' then ',
                ' later ',
                ' following ',
                ' subsequent ',
                ' prior ',
            )
        )

    @staticmethod
    def _chunk_text(chunk: DocumentChunk) -> str:
        document = chunk.document
        return ' '.join(
            part.lower()
            for part in [
                document.file_name if document else '',
                document.file_path if document else '',
                chunk.section_title or '',
                chunk.content,
            ]
            if part
        )

    @classmethod
    def _contextual_score(
        cls,
        *,
        chunk: DocumentChunk,
        years: list[str],
        employment_question: bool,
    ) -> float:
        haystack = cls._chunk_text(chunk)
        if not haystack:
            return 0.0

        score = 0.0
        if years:
            if all(cls._text_supports_year(haystack, year) for year in years):
                score += 0.22
            elif _YEAR_RE.search(haystack):
                score -= 0.40

        has_employment_markers = bool(_EMPLOYMENT_HINT_RE.search(haystack))
        has_education_markers = bool(_EDUCATION_HINT_RE.search(haystack))
        if employment_question:
            if has_employment_markers:
                score += 0.18
            if has_education_markers and not has_employment_markers:
                score -= 0.24
            if years and has_employment_markers and all(cls._text_supports_year(haystack, year) for year in years):
                score += 0.08

        return score

    def _keyword_score(self, keyword_terms: list[str], chunk: DocumentChunk) -> float:
        haystack = self._chunk_text(chunk)
        if not haystack or not keyword_terms:
            return 0.0

        token_matches = sum(1 for term in keyword_terms if term in haystack)
        phrase_matches = sum(
            1
            for left, right in zip(keyword_terms, keyword_terms[1:])
            if f'{left} {right}' in haystack
        )
        coverage = token_matches / max(len(keyword_terms), 1)
        phrase_bonus = 0.25 * (phrase_matches / max(len(keyword_terms) - 1, 1))
        score = coverage + phrase_bonus
        if token_matches >= 2 and phrase_matches >= 1:
            score += 0.15
        if any(term.isdigit() and term in haystack for term in keyword_terms):
            score += 0.05
        return min(0.999, max(0.0, score))
