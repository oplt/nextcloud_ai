from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..ai.citations import build_snippet
from ..ai.embedding_client import EmbeddingClientFactory, EmbeddingClientProtocol
from ..core import observability
from ..core.config import settings
from ..core.security import AuthContext
from ..db.models import DocumentChunk
from ..db.repo.document import DocumentChunkRepository
from ..db.repo.intelligence import KnowledgeGraphRepository
from ..rag.retriever import HybridRetriever
from ..rag.stores import RetrievalCandidate
from ..schemas.chat_schema import ChatSource, RetrievalFilters

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
_ABSOLUTE_MIN_SCORE = 0.35
_NARROW_CONFIDENCE_THRESHOLD = 0.42
_MAX_CHUNKS_PER_DOCUMENT = 3
_MAX_CONTEXTUAL_CHUNKS_PER_DOCUMENT = 4


def _looks_like_filename_query(question: str) -> bool:
    lowered = question.lower()
    return any(
        marker in lowered
        for marker in (
            "invoice",
            "factuur",
            "receipt",
            "contract",
            "agreement",
            "document",
            "file",
            "pdf",
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".odt",
            ".ods",
            ".odp",
        )
    )


@dataclass(slots=True)
class RetrievalResult:
    sources: list[ChatSource]
    query_embedding: list[float]
    grounded_document_ids: list[UUID] = field(default_factory=list)
    retrieval_debug: dict[str, object] = field(default_factory=dict)


class RetrievalService:
    def __init__(
        self,
        session: AsyncSession,
        embedding_client: EmbeddingClientProtocol | None = None,
    ) -> None:
        self.session = session
        self.embedding_client = embedding_client or EmbeddingClientFactory.create()
        self.chunk_repo = DocumentChunkRepository(session)
        self.graph_repo = KnowledgeGraphRepository(session)

    async def retrieve(
        self,
        *,
        question: str,
        auth: AuthContext,
        top_k: int = 6,
        document_ids: list[UUID] | None = None,
        preferred_document_ids: list[UUID] | None = None,
        filters: RetrievalFilters | None = None,
    ) -> RetrievalResult:
        retrieval_debug: dict[str, object] = {
            "graph_expansion_preferred": {"applied": False, "related_added": 0},
            "graph_expansion_broad": {"applied": False, "related_added": 0},
            "hybrid": {},
            "multi_evidence_question": _question_needs_multi_evidence(question),
        }
        _emb_started = time.perf_counter()
        try:
            query_embedding = await self.embedding_client.embed_query(question)
        except Exception:
            observability.record_rag_embedding_latency(
                seconds=time.perf_counter() - _emb_started,
                outcome="error",
            )
            raise
        else:
            observability.record_rag_embedding_latency(
                seconds=time.perf_counter() - _emb_started,
                outcome="success",
            )
        keyword_terms = self._extract_keyword_terms(question)
        allow_contextual_tail = _looks_like_contextual_question(question)
        multi_evidence = bool(retrieval_debug["multi_evidence_question"])

        expanded_preferred, meta_p = await self._expand_document_scope(preferred_document_ids)
        retrieval_debug["graph_expansion_preferred"] = meta_p
        expanded_document_ids = document_ids
        meta_b = {"applied": False, "related_documents_added": 0}
        retrieval_debug["graph_expansion_broad"] = meta_b

        max_chunks_narrow = self._max_chunks_per_document(
            allow_contextual_tail=allow_contextual_tail,
            multi_evidence=multi_evidence,
            top_k=top_k,
        )
        max_chunks_broad = self._max_chunks_per_document(
            allow_contextual_tail=allow_contextual_tail and bool(expanded_document_ids),
            multi_evidence=multi_evidence,
            top_k=top_k,
        )

        if expanded_preferred:
            narrow_result = await self._run_retrieval(
                question=question,
                query_embedding=query_embedding,
                keyword_terms=keyword_terms,
                auth=auth,
                top_k=top_k,
                document_ids=expanded_preferred,
                filters=filters,
                allow_semantic_context_chunks=allow_contextual_tail,
                max_chunks_per_document=max_chunks_narrow,
                retrieval_debug=retrieval_debug,
                allow_additional_documents=multi_evidence,
            )
            if narrow_result and narrow_result[0][1] >= _NARROW_CONFIDENCE_THRESHOLD:
                built = self._build_result(
                    narrow_result, query_embedding, retrieval_debug=retrieval_debug
                )
                observability.record_rag_retrieval_delivery(
                    source_count=len(built.sources),
                    retrieval_debug=built.retrieval_debug,
                )
                return built

        broad_result = await self._run_retrieval(
            question=question,
            query_embedding=query_embedding,
            keyword_terms=keyword_terms,
            auth=auth,
            top_k=top_k,
            document_ids=expanded_document_ids,
            filters=filters,
            allow_semantic_context_chunks=allow_contextual_tail and bool(expanded_document_ids),
            max_chunks_per_document=max_chunks_broad,
            retrieval_debug=retrieval_debug,
            allow_additional_documents=multi_evidence,
        )
        built = self._build_result(
            broad_result, query_embedding, retrieval_debug=retrieval_debug
        )
        observability.record_rag_retrieval_delivery(
            source_count=len(built.sources),
            retrieval_debug=built.retrieval_debug,
        )
        return built

    @staticmethod
    def _max_chunks_per_document(
        *, allow_contextual_tail: bool, multi_evidence: bool, top_k: int
    ) -> int:
        base = (
            _MAX_CONTEXTUAL_CHUNKS_PER_DOCUMENT
            if allow_contextual_tail
            else _MAX_CHUNKS_PER_DOCUMENT
        )
        if multi_evidence:
            base = max(base, min(4, top_k))
        return base



    async def _run_retrieval(
        self,
        *,
        question: str,
        query_embedding: list[float],
        keyword_terms: list[str],
        auth: AuthContext,
        top_k: int,
        document_ids: list[UUID] | None,
        filters: RetrievalFilters | None,
        allow_semantic_context_chunks: bool = False,
        max_chunks_per_document: int = _MAX_CHUNKS_PER_DOCUMENT,
        retrieval_debug: dict[str, object] | None = None,
        allow_additional_documents: bool = False,
    ) -> list[tuple[DocumentChunk, float]]:
        retriever = HybridRetriever(self.chunk_repo)
        candidates, _debug = await retriever.retrieve(
            question=question,
            query_embedding=query_embedding,
            keyword_terms=keyword_terms,
            auth=auth,
            vector_top_k=settings.RAG_VECTOR_TOP_K,
            keyword_top_k=settings.RAG_KEYWORD_TOP_K,
            rerank_top_k=settings.RAG_RERANK_TOP_K,
            final_top_n=max(settings.RAG_FINAL_TOP_N, top_k),
            document_ids=document_ids,
            filters=filters,
        )
        if retrieval_debug is not None:
            retrieval_debug["hybrid"] = _debug.as_dict()
        return self._select_grounded_chunks(
            ranked_chunks=candidates,
            keyword_terms=keyword_terms,
            top_k=top_k,
            allow_semantic_context_chunks=allow_semantic_context_chunks,
            max_chunks_per_document=max_chunks_per_document,
            allow_additional_documents=allow_additional_documents,
            allow_scoped_fallback=bool(document_ids),
        )

    @staticmethod
    def _build_result(
        grounded_chunks: list[tuple[DocumentChunk, float]],
        query_embedding: list[float],
        *,
        retrieval_debug: dict[str, object] | None = None,
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
                    heading_path=chunk.heading_path,
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
            retrieval_debug=dict(retrieval_debug or {}),
        )

    @staticmethod
    def _extract_keyword_terms(question: str) -> list[str]:
        raw_tokens = re.findall(
            r"[^\W\s]+(?:[-./][^\W\s]+)*", question, flags=re.UNICODE
        )
        tokens: list[str] = []
        for token in raw_tokens:
            lowered = token.lower()
            if len(lowered) < 2 and not any(ch.isdigit() for ch in lowered):
                continue
            if len(lowered) >= 3 and lowered in _STOPWORDS:
                continue
            tokens.append(lowered)
            for part in re.split(r"[-./_]+", lowered):
                if (
                    part
                    and part != lowered
                    and (len(part) >= 2 or any(ch.isdigit() for ch in part))
                ):
                    tokens.append(part)
        for left, right in zip(raw_tokens, raw_tokens[1:]):
            phrase = f"{left.lower()} {right.lower()}"
            if len(phrase) <= 80:
                tokens.append(phrase)
        terms: list[str] = []
        seen: set[str] = set()
        for term in tokens:
            if term in seen:
                continue
            seen.add(term)
            terms.append(term)
        return terms

    async def _expand_document_scope(
        self, document_ids: list[UUID] | None
    ) -> tuple[list[UUID] | None, dict[str, object]]:
        meta: dict[str, object] = {"applied": False, "related_documents_added": 0}
        if not document_ids:
            return document_ids, meta
        if not settings.RAG_GRAPH_EXPANSION_ENABLED:
            return document_ids, meta
        if len(document_ids) > settings.RAG_GRAPH_EXPANSION_MAX_SEED_DOCUMENTS:
            return document_ids, meta
        try:
            related_ids = await self.graph_repo.list_related_document_ids(
                document_ids=document_ids,
                limit=max(2, len(document_ids) * 2),
            )
        except (AttributeError, TypeError, ValueError):
            related_ids = []
        merged_ids: list[UUID] = []
        seen_ids: set[str] = set()
        for document_id in [*document_ids, *related_ids]:
            document_key = str(document_id)
            if document_key in seen_ids:
                continue
            seen_ids.add(document_key)
            merged_ids.append(document_id)
        if len(merged_ids) > len(document_ids):
            meta["applied"] = True
            meta["related_documents_added"] = len(merged_ids) - len(document_ids)
        return merged_ids, meta

    def _select_grounded_chunks(
        self,
        *,
        ranked_chunks: list[RetrievalCandidate],
        keyword_terms: list[str],
        top_k: int,
        allow_semantic_context_chunks: bool = False,
        max_chunks_per_document: int = _MAX_CHUNKS_PER_DOCUMENT,
        allow_additional_documents: bool = False,
        allow_scoped_fallback: bool = False,
    ) -> list[tuple[DocumentChunk, float]]:
        if not ranked_chunks:
            return []

        has_lexical_hits = any(item.lexical_score > 0 for item in ranked_chunks)
        best_score = ranked_chunks[0].score
        min_score = max(_ABSOLUTE_MIN_SCORE, best_score * 0.72)

        selected: list[tuple[DocumentChunk, float]] = []
        selected_chunk_ids: set[str] = set()
        doc_counts: dict[str, int] = {}

        for item in ranked_chunks:
            chunk = item.chunk
            document = chunk.document
            if document is None or document.is_deleted:
                continue
            filename_query = _looks_like_filename_query(" ".join(keyword_terms))
            document_text = " ".join(
                [
                    document.file_name or "",
                    document.file_path or "",
                    document.document_type or "",
                    document.business_domain or "",
                    ]
            ).lower()
            metadata_hit = any(term.lower() in document_text for term in keyword_terms)
            if filename_query and metadata_hit:
                pass
            elif item.score < _ABSOLUTE_MIN_SCORE or item.score < min_score:
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

            if (
                current_doc_count == 0
                and selected
                and not allow_additional_documents
                and not self._is_additional_document_match(
                item=item, best_score=best_score
                )
            ):
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
            if item.score < _ABSOLUTE_MIN_SCORE and not allow_scoped_fallback:
                break
            return [(chunk, item.score)]

        return []

    @staticmethod
    def _is_additional_document_match(*, item: RetrievalCandidate, best_score: float) -> bool:
        if item.score >= max(0.94, best_score - 0.03):
            return True
        if item.lexical_score >= 0.5:
            return True
        return False

def _looks_like_contextual_question(question: str) -> bool:
    lowered = f" {question.lower()} "
    return any(
        marker in lowered
        for marker in (
            " after ",
            " before ",
            " next ",
            " previous ",
            " then ",
            " later ",
            " following ",
            " subsequent ",
            " prior ",
        )
    )


def _question_needs_multi_evidence(question: str) -> bool:
    lowered = question.lower()
    return any(
        marker in lowered
        for marker in (
            "compare",
            "contrast",
            "difference",
            "differences",
            "timeline",
            "before and after",
            "pros and cons",
            "how many",
            "list all",
            "enumerate",
            "both",
            "versus",
            " vs ",
            "trade-off",
            "summarize all",
        )
    )
