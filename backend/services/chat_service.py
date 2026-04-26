from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai.citations import build_snippet
from ..ai.follow_up_classifier import FollowUpClassification
from ..ai import session_memory as chat_memory
from ..ai.llm_client import LLMClientFactory, LLMClientProtocol
from ..ai.prompt_builder import GROUNDED_PROMPT_VERSION, build_grounded_prompt
from ..ai.rag_postprocess import rerank_and_truncate_sources
from .query_writer import plan_retrieval_query
from ..core import observability
from ..core.config import settings
from ..core.exceptions import AuthorizationError, NotFoundError
from ..core.security import AuthContext
from ..db.models import ChatMessage, ChatSession, DocumentChunk, User
from ..db.repo.chat import ChatMessageRepository, ChatSessionRepository
from ..db.repo.document import DocumentChunkRepository
from ..schemas.chat_schema import (
    ChatAskRequest,
    ChatAskResponse,
    ChatDocumentResult,
    ChatMemoryPatchRequest,
    ChatSource,
)
from .audit_service import AuditService
from .document_search_service import DocumentSearchService
from .retrieval_service import RetrievalService

logger = logging.getLogger(__name__)
_CITATION_RE = re.compile(r"\[(?:source\s*)?(\d+)\]", flags=re.IGNORECASE)
_AMOUNT_QUERY_RE = re.compile(
    r"\b(amount|total|balance|due|pay|payable|paid|cost|price|invoice|factuur|bill|charge)\b",
    flags=re.IGNORECASE,
)
_MONEY_RE = re.compile(
    r"(?:€\s*\d[\d.,]*|\d[\d.,]*\s*(?:eur|euro|€))",
    flags=re.IGNORECASE,
)
_AMOUNT_CONTEXT_RE = re.compile(
    r"\b(total|amount|balance|due|payable|pay|invoice|factuur|bill|charge|incl|btw|vat|te betalen|bedrag)\b",
    flags=re.IGNORECASE,
)
_DUE_DATE_QUERY_RE = re.compile(
    r"\b(due date|deadline|payment date|pay before|pay by|te betalen voor|vervaldatum)\b|\bwhen\b.*\b(due|pay|payable)\b",
    flags=re.IGNORECASE,
)
_DATE_VALUE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b(?:19|20)\d{2}[/-]\d{1,2}[/-]\d{1,2}\b")
_DUE_DATE_CONTEXT_RE = re.compile(
    r"\b(due|deadline|payable|pay before|pay by|payment|te betalen voor|vervaldatum)\b",
    flags=re.IGNORECASE,
)
_TITLE_QUERY_RE = re.compile(
    r"\b(name|title|article|paper|publication|write|wrote|written|publish|published)\b",
    flags=re.IGNORECASE,
)
_INSUFFICIENT_MARKERS = (
    'could not verify',
    'could not find',
    'not enough',
    'insufficient',
    'do not have enough',
    'no indexed source',
    'no source',
)
_DEICTIC_FOLLOW_UP_RE = re.compile(
    r"\b(it|its|they|them|this|that|these|those|there|here|same)\b",
    flags=re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_YEAR_RANGE_RE = re.compile(
    r"\b((?:19|20)\d{2})\b.{0,48}?(?:-|to|through|until|–|—).{0,48}?\b((?:19|20)\d{2}|present|current|now)\b",
    flags=re.IGNORECASE,
)
_PIPE_RANGE_ROW_RE = re.compile(
    r"(?P<label>[^|\n]{2,120}?)\s*\|\s*(?P<context>[^|\n]{2,100}?)\s*\|\s*(?P<start>(?:[A-Z][a-z]{2,8}\s+)?(?:19|20)\d{2})\s*[-–—]\s*(?P<end>(?:(?:[A-Z][a-z]{2,8}\s+)?(?:19|20)\d{2})|present|current|now)",
    flags=re.IGNORECASE,
)
_GENERIC_QUERY_STOPWORDS = {
    "about",
    "after",
    "before",
    "could",
    "does",
    "did",
    "from",
    "give",
    "have",
    "into",
    "list",
    "show",
    "tell",
    "that",
    "the",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "name",
    "title",
    "article",
    "paper",
    "publication",
    "write",
    "wrote",
    "written",
    "publish",
    "published",
    "date",
    "due",
    "deadline",
    "payment",
    "payable",
}
_AMOUNT_QUERY_TERMS = {
    "amount",
    "total",
    "balance",
    "due",
    "pay",
    "payable",
    "paid",
    "cost",
    "price",
    "invoice",
    "factuur",
    "bill",
    "charge",
}


def _same_question_text(left: str, right: str) -> bool:
    normalize = lambda value: re.sub(r"\W+", " ", value).strip().lower()
    return normalize(left) == normalize(right)

# How many prior messages to load for context (user + assistant alternating).
_HISTORY_WINDOW = 10


class ChatService:
    def __init__(
        self,
        session: AsyncSession,
        retrieval_service: RetrievalService | None = None,
        llm_client: LLMClientProtocol | None = None,
    ) -> None:
        self.session = session
        self.retrieval_service = retrieval_service or RetrievalService(session)
        self.llm_client = llm_client or LLMClientFactory.create()
        self.session_repo = ChatSessionRepository(session)
        self.message_repo = ChatMessageRepository(session)
        self.audit = AuditService(session)

    async def _get_or_create_session(
        self, *, user: User, request: ChatAskRequest
    ) -> ChatSession:
        if request.session_id:
            return await self._get_session_for_user(request.session_id, user)

        chat_session = ChatSession(
            user_id=user.id, title=request.question.strip()[:80] or 'New chat'
        )
        await self.session_repo.add(chat_session, flush=True)
        return chat_session

    async def _get_session_for_user(
        self,
        session_id: str | UUID,
        user: User,
    ) -> ChatSession:
        existing = await self.session_repo.get(session_id)
        if existing is None:
            raise NotFoundError('Chat session not found')
        if existing.user_id != user.id:
            raise AuthorizationError('Chat session does not belong to this user')
        return existing

    @staticmethod
    def _touch_session(chat_session: ChatSession) -> None:
        chat_session.updated_at = datetime.now(timezone.utc)

    async def patch_session_memory(
        self,
        *,
        user: User,
        session_id: str | UUID,
        payload: ChatMemoryPatchRequest,
    ) -> dict[str, object]:
        chat_session = await self._get_session_for_user(session_id, user)
        mem = chat_memory.normalize_memory(getattr(chat_session, 'memory_json', None))
        if payload.clear:
            mem = chat_memory.empty_memory()
        if payload.items:
            chat_memory.apply_memory_item_patch(mem, payload.items)
        if payload.focus_lock_document_ids is not None:
            mem['focus_lock_document_ids'] = list(payload.focus_lock_document_ids)[:24]
        chat_memory.prune_expired_items(mem)
        chat_session.memory_json = dict(mem)
        self._touch_session(chat_session)
        await self.session.commit()
        return mem

    async def delete_session(self, session_id: str, actor: User) -> None:
        chat_session = await self._get_session_for_user(session_id, actor)
        await self.session_repo.delete(chat_session)
        await self.audit.log(
            action='chat.deleted',
            resource_type='chat_session',
            resource_id=str(chat_session.id),
            message='Chat session deleted',
            user=actor,
        )
        await self.session.commit()

    @staticmethod
    def _extract_preferred_document_ids(
        prior_messages_orm: list[ChatMessage],
    ) -> list[UUID]:
        for msg in reversed(prior_messages_orm):
            if msg.role != 'assistant':
                continue
            citations = msg.citations_json
            if not citations:
                continue
            seen: set[str] = set()
            ids: list[UUID] = []
            for citation in citations:
                raw_id = citation.get('document_id')
                if raw_id and str(raw_id) not in seen:
                    seen.add(str(raw_id))
                    try:
                        ids.append(UUID(str(raw_id)))
                    except ValueError:
                        pass
            if ids:
                return ids
        return []

    @staticmethod
    def _extract_preferred_chunk_refs(
        prior_messages_orm: list[ChatMessage],
    ) -> list[tuple[UUID, UUID]]:
        for msg in reversed(prior_messages_orm):
            if msg.role != 'assistant':
                continue
            citations = msg.citations_json or []
            refs: list[tuple[UUID, UUID]] = []
            seen: set[str] = set()
            for citation in citations:
                raw_chunk_id = citation.get('chunk_id')
                raw_document_id = citation.get('document_id')
                if not raw_chunk_id or not raw_document_id:
                    continue
                try:
                    chunk_id = UUID(str(raw_chunk_id))
                    document_id = UUID(str(raw_document_id))
                except ValueError:
                    continue
                key = f'{document_id}:{chunk_id}'
                if key in seen:
                    continue
                seen.add(key)
                refs.append((document_id, chunk_id))
            if refs:
                return refs
        return []

    @staticmethod
    def _looks_like_contextual_follow_up(question: str) -> bool:
        lowered = f' {question.lower()} '
        if any(marker in lowered for marker in (' after ', ' before ', ' next ', ' previous ', ' then ', ' later ', ' following ', ' subsequent ', ' prior ')):
            return True
        return bool(_DEICTIC_FOLLOW_UP_RE.search(question))

    @staticmethod
    def _neighbor_offsets_for_question(question: str) -> list[int]:
        lowered = f' {question.lower()} '
        if any(marker in lowered for marker in (' after ', ' next ', ' then ', ' later ', ' following ', ' subsequent ')):
            return [1, 2]
        if any(marker in lowered for marker in (' before ', ' previous ', ' prior ')):
            return [-1, -2]
        return [-1, 1]

    @staticmethod
    def _source_from_chunk(chunk: DocumentChunk, *, score: float) -> ChatSource:
        document = chunk.document
        file_name = document.file_name if document is not None else ''
        file_path = document.file_path if document is not None else ''
        content = chunk.content or ''
        return ChatSource(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            file_name=file_name,
            file_path=file_path,
            page_number=chunk.page_number,
            section_title=chunk.section_title,
            heading_path=chunk.heading_path,
            snippet=build_snippet(content),
            score=max(0.0, min(0.999, score)),
            distance=max(0.0, 1.0 - max(0.0, min(0.999, score))),
            content=content,
        )

    async def _augment_follow_up_sources_with_neighbors(
        self,
        *,
        question: str,
        sources: list[ChatSource],
        preferred_chunk_refs: list[tuple[UUID, UUID]],
    ) -> list[ChatSource]:
        if not sources or not preferred_chunk_refs or not self._looks_like_contextual_follow_up(question):
            return sources

        offsets = self._neighbor_offsets_for_question(question)
        base_score = max((source.score for source in sources), default=0.72)
        by_doc_chunks: dict[str, list[DocumentChunk]] = {}
        existing_ids = {str(source.chunk_id) for source in sources}
        neighbor_sources: list[ChatSource] = []

        chunk_repo = DocumentChunkRepository(self.session)
        for document_id, chunk_id in preferred_chunk_refs:
            doc_key = str(document_id)
            if doc_key not in by_doc_chunks:
                by_doc_chunks[doc_key] = await chunk_repo.list_by_document(document_id)
            chunks = by_doc_chunks[doc_key]
            index_by_chunk_id = {str(chunk.id): idx for idx, chunk in enumerate(chunks)}
            anchor_index = index_by_chunk_id.get(str(chunk_id))
            if anchor_index is None:
                continue
            for rank, offset in enumerate(offsets, start=1):
                candidate_index = anchor_index + offset
                if candidate_index < 0 or candidate_index >= len(chunks):
                    continue
                candidate = chunks[candidate_index]
                candidate_key = str(candidate.id)
                if candidate_key in existing_ids:
                    continue
                existing_ids.add(candidate_key)
                neighbor_sources.append(
                    self._source_from_chunk(
                        candidate,
                        score=base_score - 0.01 * rank,
                    )
                )

        if not neighbor_sources:
            return sources

        if offsets and offsets[0] > 0:
            return [*neighbor_sources, *sources]
        return [*sources, *neighbor_sources]

    async def _build_follow_up_neighbor_sources(
        self,
        *,
        question: str,
        preferred_chunk_refs: list[tuple[UUID, UUID]],
    ) -> list[ChatSource]:
        if not preferred_chunk_refs or not self._looks_like_contextual_follow_up(question):
            return []

        offsets = self._neighbor_offsets_for_question(question)
        chunk_repo = DocumentChunkRepository(self.session)
        by_doc_chunks: dict[str, list[DocumentChunk]] = {}
        sources: list[ChatSource] = []
        seen_chunk_ids: set[str] = set()

        for document_id, chunk_id in preferred_chunk_refs:
            doc_key = str(document_id)
            if doc_key not in by_doc_chunks:
                by_doc_chunks[doc_key] = await chunk_repo.list_by_document(document_id)
            chunks = by_doc_chunks[doc_key]
            index_by_chunk_id = {str(chunk.id): idx for idx, chunk in enumerate(chunks)}
            anchor_index = index_by_chunk_id.get(str(chunk_id))
            if anchor_index is None:
                continue
            for rank, offset in enumerate(offsets, start=1):
                candidate_index = anchor_index + offset
                if candidate_index < 0 or candidate_index >= len(chunks):
                    continue
                candidate = chunks[candidate_index]
                candidate_key = str(candidate.id)
                if candidate_key in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(candidate_key)
                sources.append(
                    self._source_from_chunk(
                        candidate,
                        score=max(0.5, 0.86 - 0.04 * rank),
                    )
                )

        return sources

    async def _augment_question_sources_from_same_documents(
        self,
        *,
        question: str,
        sources: list[ChatSource],
        max_sources: int,
    ) -> list[ChatSource]:
        if not sources:
            return sources
        years = self._requested_years(question)
        query_terms = self._generic_query_terms(question)
        if not years and not query_terms:
            return sources

        chunk_repo = DocumentChunkRepository(self.session)
        existing_ids = {str(source.chunk_id) for source in sources}
        document_ids: list[UUID] = []
        seen_documents: set[str] = set()
        source_chunk_ids_by_document: dict[str, set[str]] = {}
        for source in sources:
            document_key = str(source.document_id)
            source_chunk_ids_by_document.setdefault(document_key, set()).add(
                str(source.chunk_id)
            )
            if document_key in seen_documents:
                continue
            seen_documents.add(document_key)
            document_ids.append(UUID(document_key))

        boosted_sources: list[tuple[float, ChatSource]] = []
        base_score = max((source.score for source in sources), default=0.72)
        for document_id in document_ids[:3]:
            chunks = await chunk_repo.list_by_document(document_id)
            document_key = str(document_id)
            anchor_chunk_ids = source_chunk_ids_by_document.get(document_key, set())
            anchor_indexes = {
                chunk.chunk_index for chunk in chunks if str(chunk.id) in anchor_chunk_ids
            }
            for chunk in chunks:
                chunk_key = str(chunk.id)
                if chunk_key in existing_ids:
                    continue
                source = self._source_from_chunk(chunk, score=max(0.5, base_score - 0.01))
                relevance = self._same_document_chunk_relevance(
                    question_terms=query_terms,
                    years=years,
                    source=source,
                    chunk=chunk,
                    anchor_indexes=anchor_indexes,
                )
                if years and self._source_supports_years(source, years):
                    boosted_sources.append((relevance + 10.0, source))
                    existing_ids.add(chunk_key)
                    continue
                if relevance > 0:
                    boosted_sources.append((relevance, source))
                    existing_ids.add(chunk_key)

        if not boosted_sources:
            return sources
        boosted_sources.sort(key=lambda item: item[0], reverse=True)
        return [source for _, source in boosted_sources[:max_sources]] + sources

    @staticmethod
    def _generic_query_terms(question: str) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for token in re.findall(r"[^\W\s]+", question.lower(), flags=re.UNICODE):
            if token in _GENERIC_QUERY_STOPWORDS:
                continue
            if len(token) < 3 and not any(ch.isdigit() for ch in token):
                continue
            if token in seen:
                continue
            seen.add(token)
            terms.append(token)
        return terms

    @classmethod
    def _same_document_chunk_relevance(
        cls,
        *,
        question_terms: list[str],
        years: list[int],
        source: ChatSource,
        chunk: DocumentChunk,
        anchor_indexes: set[int],
    ) -> float:
        text = " ".join(
            [
                chunk.content or "",
                chunk.section_title or "",
                chunk.heading_path or "",
                source.file_name or "",
                source.file_path or "",
            ]
        ).lower()
        score = 0.0
        if question_terms:
            score += sum(1.0 for term in question_terms if term in text)
        if years and cls._source_supports_years(source, years):
            score += 4.0
        if _AMOUNT_QUERY_RE.search(" ".join(question_terms)) and _MONEY_RE.search(text):
            score += 3.0
            if _AMOUNT_CONTEXT_RE.search(text):
                score += 2.0
        if anchor_indexes:
            nearest = min(
                abs(chunk.chunk_index - anchor)
                for anchor in anchor_indexes
                if anchor >= 0
            ) if any(anchor >= 0 for anchor in anchor_indexes) else None
            if nearest is not None and nearest <= 16:
                score += max(0.2, 2.0 / (nearest + 1))
        return score

    @staticmethod
    def _parse_active_context_document_ids(document_ids: list[str] | None) -> list[UUID]:
        parsed_ids: list[UUID] = []
        seen_ids: set[str] = set()
        for raw_id in document_ids or []:
            if not raw_id:
                continue
            try:
                parsed_id = UUID(str(raw_id))
            except ValueError:
                continue
            parsed_key = str(parsed_id)
            if parsed_key in seen_ids:
                continue
            seen_ids.add(parsed_key)
            parsed_ids.append(parsed_id)
        return parsed_ids

    @staticmethod
    def _merge_document_ids(*document_groups: list[UUID]) -> list[UUID]:
        merged_ids: list[UUID] = []
        seen_ids: set[str] = set()
        for group in document_groups:
            for document_id in group:
                document_key = str(document_id)
                if document_key in seen_ids:
                    continue
                seen_ids.add(document_key)
                merged_ids.append(document_id)
        return merged_ids

    @staticmethod
    def _extract_document_ids_from_sources(sources: list[ChatSource]) -> list[UUID]:
        document_ids: list[UUID] = []
        seen_ids: set[str] = set()
        for source in sources:
            document_key = str(source.document_id)
            if document_key in seen_ids:
                continue
            seen_ids.add(document_key)
            document_ids.append(UUID(document_key))
        return document_ids

    @staticmethod
    def _build_active_context_documents(
        sources: list[ChatSource],
        active_document_ids: list[UUID],
    ) -> list[dict[str, str]]:
        source_documents: dict[str, dict[str, str]] = {}
        for source in sources:
            document_key = str(source.document_id)
            if document_key in source_documents:
                continue
            source_documents[document_key] = {
                'document_id': document_key,
                'file_name': source.file_name,
                'file_path': source.file_path,
            }

        documents: list[dict[str, str]] = []
        for document_id in active_document_ids:
            document_payload = source_documents.get(str(document_id))
            if document_payload is not None:
                documents.append(document_payload)
        return documents

    @staticmethod
    def _build_no_sources_answer() -> str:
        return (
            'I could not find indexed source material for that question. '
            'The relevant file may not be synced yet, may not have been chunked and embedded, '
            'or you may not have access to it.'
        )

    @staticmethod
    def _build_document_search_answer(results: list[ChatDocumentResult]) -> str:
        lines = ["I found these matching documents:"]
        for index, item in enumerate(results[:8], start=1):
            lines.append(f"[{index}] {item.file_name} - {item.file_path}")
        return "\n".join(lines)

    @staticmethod
    def _build_empty_answer() -> str:
        return (
            'I could not produce an answer because the language model returned an empty response. '
            'Your question was saved in the chat history.'
        )

    @staticmethod
    def _extract_upstream_error_detail(exc: httpx.HTTPStatusError) -> str:
        detail: str | None = None
        try:
            payload = exc.response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            for key in ('error', 'detail', 'message'):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    detail = value.strip()
                    break

        if detail is None:
            response_text = exc.response.text.strip()
            if response_text:
                detail = response_text

        if detail is None:
            detail = f'HTTP {exc.response.status_code}'

        return ' '.join(detail.split())

    def _build_failure_answer(self, exc: Exception) -> str:
        if isinstance(exc, httpx.TimeoutException):
            return (
                'I could not answer because the embedding or language model request timed out. '
                'Your question was saved in the chat history.'
            )
        if isinstance(exc, httpx.HTTPStatusError):
            detail = self._extract_upstream_error_detail(exc)
            return (
                'I could not answer because the AI backend returned an error: '
                f'{detail}. Your question was saved in the chat history.'
            )
        if isinstance(exc, httpx.RequestError):
            return (
                'I could not answer because the embedding or language model service was unreachable. '
                'Your question was saved in the chat history.'
            )
        return (
            'I could not answer because the retrieval or generation pipeline failed. '
            'Your question was saved in the chat history.'
        )

    @staticmethod
    def _filter_sources_to_citations(
        answer: str, sources: list[ChatSource]
    ) -> tuple[str, list[ChatSource]]:
        if not sources:
            return answer, []

        cited_indexes: list[int] = []
        seen_indexes: set[int] = set()
        for match in _CITATION_RE.finditer(answer):
            source_index = int(match.group(1))
            if source_index < 1 or source_index > len(sources):
                continue
            if source_index in seen_indexes:
                continue
            seen_indexes.add(source_index)
            cited_indexes.append(source_index)

        if not cited_indexes:
            return answer, []

        remapped_indexes = {
            original: new
            for new, original in enumerate(cited_indexes, start=1)
        }

        filtered_sources = [sources[idx - 1] for idx in cited_indexes]
        normalized_answer = _CITATION_RE.sub(
            lambda m: (
                f"[{remapped_indexes[int(m.group(1))]}]"
                if int(m.group(1)) in remapped_indexes
                else ''
            ),
            answer,
        )
        normalized_answer = re.sub(r'\s{2,}', ' ', normalized_answer).strip()
        return normalized_answer, filtered_sources

    @staticmethod
    def _answer_style_rules(question: str) -> list[str]:
        if not _AMOUNT_QUERY_RE.search(question):
            return []
        return [
            "For amount, total, balance, payable, invoice, bill, cost, or price questions: answer with the exact amount first.",
            "Prefer the payable/total/invoice amount over tariffs, rates, fees, background, or explanatory text unless the user asks for those.",
            "Keep amount answers to one short sentence when one amount directly answers the question.",
        ]

    @staticmethod
    def _source_evidence_text(source: ChatSource) -> str:
        return " ".join(
            [
                source.content or "",
                source.snippet or "",
                source.section_title or "",
                source.heading_path or "",
                source.file_name or "",
                source.file_path or "",
            ]
        )

    @classmethod
    def _source_evidence_lines(cls, source: ChatSource) -> list[str]:
        text = "\n".join(
            [
                source.content or "",
                source.snippet or "",
                source.section_title or "",
                source.heading_path or "",
            ]
        )
        lines: list[str] = []
        for raw_line in text.splitlines():
            line = " ".join(raw_line.split()).strip()
            if line:
                lines.append(line)
        if not lines and text.strip():
            lines.append(" ".join(text.split()))
        return lines

    @classmethod
    def _build_direct_answer(
        cls, *, question: str, sources: list[ChatSource], trace_id: str
    ) -> tuple[str, list[ChatSource], dict[str, object]] | None:
        title_answer = cls._build_direct_title_answer(question=question, sources=sources)
        if title_answer is not None:
            answer, cited_sources = title_answer
            return answer, cited_sources, {
                "result": "direct_extraction",
                "direct_extraction_type": "title",
                "trace_id": trace_id,
                "shadow_mode": False,
            }

        due_date_answer = cls._build_direct_due_date_answer(question=question, sources=sources)
        if due_date_answer is not None:
            answer, cited_sources = due_date_answer
            return answer, cited_sources, {
                "result": "direct_extraction",
                "direct_extraction_type": "due_date",
                "trace_id": trace_id,
                "shadow_mode": False,
            }

        amount_answer = cls._build_direct_amount_answer(question=question, sources=sources)
        if amount_answer is not None:
            answer, cited_sources = amount_answer
            return answer, cited_sources, {
                "result": "direct_extraction",
                "direct_extraction_type": "amount",
                "trace_id": trace_id,
                "shadow_mode": False,
            }

        range_answer = cls._build_direct_range_answer(question=question, sources=sources)
        if range_answer is not None:
            answer, cited_sources = range_answer
            return answer, cited_sources, {
                "result": "direct_extraction",
                "direct_extraction_type": "date_range_rows",
                "trace_id": trace_id,
                "shadow_mode": False,
            }
        return None

    @classmethod
    def _build_direct_due_date_answer(
        cls, *, question: str, sources: list[ChatSource]
    ) -> tuple[str, list[ChatSource]] | None:
        if not _DUE_DATE_QUERY_RE.search(question):
            return None
        entity_terms = cls._direct_answer_entity_terms(question)
        best: tuple[float, str, ChatSource] | None = None
        for source in sources:
            text = cls._source_evidence_text(source)
            if not text:
                continue
            entity_score = cls._entity_match_score(entity_terms, text)
            if entity_terms and entity_score <= 0:
                continue
            for match in _DATE_VALUE_RE.finditer(text):
                start = max(0, match.start() - 90)
                end = min(len(text), match.end() + 90)
                context = text[start:end]
                score = source.score + entity_score * 5.0
                if _DUE_DATE_CONTEXT_RE.search(context):
                    score += 5.0
                if re.search(r"\b(te betalen voor|pay before|pay by|due date|vervaldatum)\b", context, flags=re.IGNORECASE):
                    score += 10.0
                if re.search(r"\bfactuurdatum\b", context, flags=re.IGNORECASE):
                    score -= 6.0
                candidate = (score, match.group(0), source)
                if best is None or candidate[0] > best[0]:
                    best = candidate
        if best is None:
            return None
        _score, due_date, source = best
        return f"{due_date} [1]", [source]

    @classmethod
    def _build_direct_title_answer(
        cls, *, question: str, sources: list[ChatSource]
    ) -> tuple[str, list[ChatSource]] | None:
        if not _TITLE_QUERY_RE.search(question):
            return None
        years = cls._requested_years(question)
        best: tuple[float, str, ChatSource] | None = None
        for source in sources:
            if years and not cls._source_supports_years(source, years):
                continue
            title = cls._title_from_source(source)
            if title is None:
                continue
            score = source.score
            if years:
                score += 3.0
            if re.search(r"\b(article|paper|journal|publication)\b", cls._source_evidence_text(source), flags=re.IGNORECASE):
                score += 2.0
            candidate = (score, title, source)
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is None:
            return None
        _score, title, source = best
        return f"{title} [1]", [source]

    @staticmethod
    def _title_from_source(source: ChatSource) -> str | None:
        candidates = [source.file_name or "", source.heading_path or "", source.section_title or ""]
        for candidate in candidates:
            value = candidate.strip()
            if not value:
                continue
            if "/" in value:
                value = value.split("/")[-1].strip()
            value = re.sub(r"\.(pdf|docx?|odt|txt|md)$", "", value, flags=re.IGNORECASE).strip()
            value = re.split(r"\s*>\s*", value)[0].strip()
            value = re.sub(r"\s*-\s+", ": ", value).strip(" :-")
            if len(value) >= 8 and not value.lower() in {"introduction", "appendix"}:
                return value
        return None

    @classmethod
    def _build_direct_amount_answer(
        cls, *, question: str, sources: list[ChatSource]
    ) -> tuple[str, list[ChatSource]] | None:
        if _DUE_DATE_QUERY_RE.search(question):
            return None
        if not _AMOUNT_QUERY_RE.search(question):
            return None
        entity_terms = cls._direct_answer_entity_terms(question)
        best: tuple[float, str, ChatSource] | None = None
        for source in sources:
            text = cls._source_evidence_text(source)
            if not text:
                continue
            entity_score = cls._entity_match_score(entity_terms, text)
            if entity_terms and entity_score <= 0:
                continue
            for match in _MONEY_RE.finditer(text):
                amount = " ".join(match.group(0).replace("€", " EUR").split())
                start = max(0, match.start() - 80)
                end = min(len(text), match.end() + 80)
                context = text[start:end]
                score = source.score + entity_score * 5.0
                if _AMOUNT_CONTEXT_RE.search(context):
                    score += 3.0
                if re.search(r"\b(te betalen|payable|total|invoice total|factuur.*bedrag|bedrag)\b", context, flags=re.IGNORECASE):
                    score += 4.0
                if amount.lower().startswith("eur"):
                    amount = amount[3:].strip() + " EUR"
                candidate = (score, amount, source)
                if best is None or candidate[0] > best[0]:
                    best = candidate
        if best is None:
            return None
        _score, amount, source = best
        return f"{amount} [1]", [source]

    @classmethod
    def _build_direct_range_answer(
        cls, *, question: str, sources: list[ChatSource]
    ) -> tuple[str, list[ChatSource]] | None:
        years = cls._requested_years(question)
        if len(years) < 2:
            return None
        query_start, query_end = min(years), max(years)
        matches: list[tuple[str, str, str, ChatSource, int, int]] = []
        seen: set[tuple[str, str, str]] = set()
        for source in sources:
            for line in cls._source_evidence_lines(source):
                for match in _PIPE_RANGE_ROW_RE.finditer(line):
                    label = " ".join(match.group("label").split()).strip(":- ")
                    context = " ".join(match.group("context").split()).strip(":- ")
                    if not cls._looks_like_clean_range_label(label):
                        continue
                    if not cls._looks_like_clean_range_label(context, allow_short=True):
                        continue
                    start_year = cls._first_year(match.group("start"))
                    end_year = cls._first_year(match.group("end")) or 9999
                    if start_year is None:
                        continue
                    if end_year < query_start or start_year > query_end:
                        continue
                    date_range = f"{match.group('start').strip()} - {match.group('end').strip()}"
                    key = (label.lower(), context.lower(), date_range.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    matches.append((label, context, date_range, source, start_year, end_year))
        if not matches:
            return None
        matches.sort(key=lambda item: (item[4], item[5], item[0].lower()))
        matches = matches[:6]
        cited_sources = [item[3] for item in matches]
        lines = [
            f"- {label} ({context}, {date_range}) [{index}]"
            for index, (label, context, date_range, _source, _start, _end) in enumerate(matches, start=1)
        ]
        return "\n".join(lines), cited_sources

    @classmethod
    def _direct_answer_entity_terms(cls, question: str) -> list[str]:
        return [
            term
            for term in cls._generic_query_terms(question)
            if term not in _AMOUNT_QUERY_TERMS
        ]

    @staticmethod
    def _entity_match_score(entity_terms: list[str], text: str) -> float:
        if not entity_terms:
            return 0.0
        normalized = re.sub(r"[^a-z0-9]+", "", text.lower())
        score = 0.0
        for term in entity_terms:
            compact = re.sub(r"[^a-z0-9]+", "", term.lower())
            if not compact:
                continue
            if compact in normalized:
                score += 1.0
            elif len(compact) >= 6 and compact[:6] in normalized:
                score += 0.7
        return score

    @staticmethod
    def _looks_like_clean_range_label(value: str, *, allow_short: bool = False) -> bool:
        cleaned = value.strip()
        if len(cleaned) < (2 if allow_short else 3) or len(cleaned) > 90:
            return False
        if any(marker in cleaned for marker in ("●", "Context above", "Context below", "Extracted table facts")):
            return False
        return True

    @staticmethod
    def _first_year(text: str) -> int | None:
        match = _YEAR_RE.search(text)
        if match is None:
            return None
        return int(match.group(0))

    @staticmethod
    def _is_insufficient_answer(answer: str) -> bool:
        lowered = f" {answer.lower()} "
        return any(marker in lowered for marker in _INSUFFICIENT_MARKERS)

    @staticmethod
    def _strip_leading_question_echo(*, question: str, answer: str) -> str:
        cleaned_answer = answer.strip()
        cleaned_question = question.strip()
        if not cleaned_answer or not cleaned_question:
            return cleaned_answer

        label_match = re.match(
            r"^(?:question|q)\s*[:：]\s*(.+?)(?:\n+|(?:\s+(?:answer|a)\s*[:：]\s+))(.+)$",
            cleaned_answer,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if label_match:
            possible_question = label_match.group(1).strip()
            possible_answer = label_match.group(2).strip()
            if _same_question_text(possible_question, cleaned_question) and possible_answer:
                return possible_answer

        candidates = {
            cleaned_question,
            cleaned_question.rstrip(" ?!.:："),
        }
        for candidate in sorted(candidates, key=len, reverse=True):
            if not candidate:
                continue
            if cleaned_answer.lower().startswith(candidate.lower()):
                remainder = cleaned_answer[len(candidate):].strip()
                remainder = re.sub(
                    r"^(?:[?？!.。:：\-–—]+|\banswer\s*[:：])\s*",
                    "",
                    remainder,
                    flags=re.IGNORECASE,
                )
                if remainder:
                    return remainder
        return cleaned_answer

    @classmethod
    def _prioritize_sources_for_question(
        cls,
        *,
        question: str,
        sources: list[ChatSource],
    ) -> list[ChatSource]:
        del question
        return sorted(sources, key=lambda source: source.score, reverse=True)

    @staticmethod
    def _looks_like_claim_challenge(question: str) -> bool:
        lowered = f" {question.lower()} "
        challenge_terms = (' not ', ' never ', ' wrong ', ' incorrect ', ' are you sure ', ' he never ', ' she never ')
        return any(term in lowered for term in challenge_terms)

    @staticmethod
    def _source_texts(sources: list[ChatSource]) -> list[str]:
        texts: list[str] = []
        for source in sources:
            source_text = (source.content or source.snippet or '').strip()
            if source_text:
                texts.append(f" {source_text.lower()} ")
        return texts

    @staticmethod
    def _requested_years(question: str) -> list[int]:
        years: list[int] = []
        seen: set[int] = set()
        for match in _YEAR_RE.finditer(question):
            year = int(match.group(0))
            if year in seen:
                continue
            seen.add(year)
            years.append(year)
        return years

    @staticmethod
    def _source_supports_years(source: ChatSource, years: list[int]) -> bool:
        if not years:
            return True
        text = " ".join(
            [
                source.content or "",
                source.snippet or "",
                source.file_name or "",
                source.file_path or "",
                source.section_title or "",
                source.heading_path or "",
            ]
        ).lower()
        if not text:
            return False
        exact_years = {int(match.group(0)) for match in _YEAR_RE.finditer(text)}
        ranges: list[tuple[int, int]] = []
        for match in _YEAR_RANGE_RE.finditer(text):
            start = int(match.group(1))
            end_raw = match.group(2).lower()
            end = 9999 if end_raw in {"present", "current", "now"} else int(end_raw)
            if end < start:
                start, end = end, start
            ranges.append((start, end))
        for year in years:
            if year in exact_years:
                continue
            if any(start <= year <= end for start, end in ranges):
                continue
            return False
        return True

    @classmethod
    def _filter_sources_for_question_constraints(
        cls, *, question: str, sources: list[ChatSource]
    ) -> tuple[list[ChatSource], dict[str, object]]:
        years = cls._requested_years(question)
        if not years:
            return sources, {"time_filter_applied": False}
        filtered = [
            source for source in sources if cls._source_supports_years(source, years)
        ]
        if not filtered:
            return sources, {
                "time_filter_applied": False,
                "time_filter_relaxed": True,
                "requested_years": years,
                "before": len(sources),
                "after": 0,
            }
        return filtered, {
            "time_filter_applied": True,
            "requested_years": years,
            "before": len(sources),
            "after": len(filtered),
        }

    def _answer_is_supported(
        self,
        *,
        question: str,
        answer: str,
        cited_sources: list[ChatSource],
    ) -> bool:
        if not cited_sources:
            return False
        if self._is_insufficient_answer(answer):
            return True

        source_texts = self._source_texts(cited_sources)
        if not source_texts:
            return False

        years = self._requested_years(question)
        if years and not all(
            self._source_supports_years(source, years) for source in cited_sources
        ):
            return False
        return True

    @classmethod
    def _select_supporting_sources(
        cls,
        *,
        question: str,
        answer: str,
        sources: list[ChatSource],
        max_sources: int = 2,
    ) -> list[ChatSource]:
        if not sources:
            return []

        source_texts = [
            ((source.content or source.snippet or '').strip().lower(), source)
            for source in sources
        ]
        source_texts = [(text, source) for text, source in source_texts if text]
        if not source_texts:
            return []

        years = cls._requested_years(question)
        if years:
            source_texts = [
                (text, source)
                for text, source in source_texts
                if cls._source_supports_years(source, years)
            ]
            if not source_texts:
                return []

        del answer
        supporting: list[ChatSource] = []
        for text, source in source_texts:
            del text
            supporting.append(source)
            if len(supporting) >= max_sources:
                break

        if supporting:
            return supporting
        return [source_texts[0][1]]

    @staticmethod
    def _append_citations(answer: str, count: int) -> str:
        trimmed = answer.strip()
        if not trimmed or count <= 0:
            return trimmed
        suffix = ''.join(f'[{index}]' for index in range(1, count + 1))
        return f'{trimmed} {suffix}'

    @staticmethod
    def _build_source_fallback_answer(sources: list[ChatSource]) -> str:
        if not sources:
            return (
                'I could not answer because the embedding or language model request timed out. '
                'Your question was saved in the chat history.'
            )
        cited_bits: list[str] = []
        for index, source in enumerate(sources[:2], start=1):
            text = (source.content or source.snippet or '').strip()
            if not text:
                continue
            cited_bits.append(f'{build_snippet(text, limit=280)} [{index}]')
        if not cited_bits:
            return (
                'I found source material, but could not summarize it because the language model timed out.'
            )
        return 'I found relevant indexed source material: ' + ' '.join(cited_bits)

    def _build_unverified_answer(self, question: str) -> str:
        if self._looks_like_claim_challenge(question):
            return 'I could not verify that claim from the indexed sources.'
        return 'I could not verify that from the indexed sources.'

    def _llm_model_id(self) -> str:
        client = self.llm_client
        model = getattr(client, 'model', None)
        if model is not None:
            return str(model)
        return 'stub'

    def _retrieval_settings_snapshot(
        self,
        *,
        request: ChatAskRequest,
        retrieval_query: str,
        is_follow_up: bool,
        follow_up: FollowUpClassification | None = None,
    ) -> dict[str, object]:
        filters_dump: object = None
        if request.retrieval_filters is not None:
            filters_dump = request.retrieval_filters.model_dump(mode='json')
        snap: dict[str, object] = {
            'top_k': request.top_k,
            'document_ids': [str(d) for d in (request.document_ids or [])],
            'retrieval_filters': filters_dump,
            'active_context_document_ids': list(request.active_context_document_ids or []),
            'is_follow_up': is_follow_up,
            'retrieval_query': retrieval_query,
        }
        if follow_up is not None:
            snap['follow_up_confidence'] = follow_up.confidence
            snap['follow_up_reasons'] = list(follow_up.reasons)
        return snap

    @staticmethod
    def _compute_answer_confidence(
        sources: list[ChatSource],
        verification_summary: dict[str, object] | None,
    ) -> float | None:
        if verification_summary is None:
            return None
        result = verification_summary.get('result')
        top = max((s.score for s in sources), default=0.0)
        if result == 'passed':
            return round(min(0.99, 0.52 + 0.42 * top), 3)
        if result in {'insufficient_answer', 'empty_llm'}:
            return round(0.15 + 0.25 * top, 3)
        if result in {'no_sources', 'no_inline_citations', 'support_check_failed'}:
            return round(0.12 + 0.2 * top, 3)
        return round(0.2 + 0.15 * top, 3)

    async def _maybe_summarize_session(
        self,
        *,
        chat_session: ChatSession,
        messages: list[ChatMessage],
        mem: dict[str, object],
    ) -> None:
        if len(messages) < settings.RAG_SESSION_SUMMARY_MESSAGE_THRESHOLD:
            return
        head = messages[: max(0, len(messages) - 8)]
        if len(head) < 6:
            return
        lines = [f'{m.role}: {m.content[:520]}' for m in head]
        prompt = (
            'Summarize durable facts and unresolved threads from this chat prefix '
            'in 4-6 sentences for future turns. Do not invent facts.\n\n'
            + '\n'.join(lines)
        )
        try:
            summary = (await self.llm_client.generate(prompt)).strip()
            if summary:
                mem['session_summary'] = summary[:4000]
                chat_session.memory_json = dict(mem)
        except Exception:
            logger.exception(
                'chat.session_summary_failed session=%s', chat_session.id
            )

    def _verify_and_normalize_answer(
        self,
        *,
        question: str,
        answer: str,
        sources: list[ChatSource],
        shadow_mode: bool,
        trace_id: str,
    ) -> tuple[str, list[ChatSource], dict[str, object]]:
        verification: dict[str, object] = {
            'shadow_mode': shadow_mode,
            'trace_id': trace_id,
        }
        if answer == self._build_empty_answer():
            verification['result'] = 'empty_llm'
            return answer, sources, verification

        answer = self._strip_leading_question_echo(question=question, answer=answer)

        normalized_answer, cited_sources = self._filter_sources_to_citations(answer, sources)
        if self._is_insufficient_answer(normalized_answer):
            verification['result'] = 'insufficient_answer'
            supporting_sources = cited_sources or self._select_supporting_sources(
                question=question,
                answer=normalized_answer,
                sources=sources,
                max_sources=4,
            )
            return normalized_answer, supporting_sources, verification

        if not cited_sources:
            supporting_sources = self._select_supporting_sources(
                question=question,
                answer=normalized_answer,
                sources=sources,
            )
            if supporting_sources and self._answer_is_supported(
                question=question,
                answer=normalized_answer,
                cited_sources=supporting_sources,
            ):
                verification['result'] = 'auto_cited'
                verification['auto_citation_applied'] = True
                verification['auto_citation_count'] = len(supporting_sources)
                return (
                    self._append_citations(normalized_answer, len(supporting_sources)),
                    supporting_sources,
                    verification,
                )

            strict_answer = self._build_unverified_answer(question)
            verification['result'] = 'no_inline_citations'
            verification['strict_answer_would_be'] = strict_answer
            if shadow_mode:
                verification['shadow_kept_raw'] = True
                logger.warning(
                    'chat.verification.shadow_skip_no_citations %s',
                    json.dumps({'trace_id': trace_id}),
                )
                return answer.strip(), [], verification
            return strict_answer, [], verification

        support = self._answer_is_supported(
            question=question, answer=normalized_answer, cited_sources=cited_sources
        )
        verification['support_check_passed'] = support
        if not support:
            strict_answer = self._build_unverified_answer(question)
            verification['result'] = 'support_check_failed'
            verification['strict_answer_would_be'] = strict_answer
            if shadow_mode:
                verification['shadow_keeps_citation_answer'] = True
                logger.warning(
                    'chat.verification.shadow_skip_support_check %s',
                    json.dumps({'trace_id': trace_id, 'question': question[:240]}),
                )
                return normalized_answer, cited_sources, verification
            return strict_answer, [], verification

        verification['result'] = 'passed'
        return normalized_answer, cited_sources, verification

    async def ask(
        self, *, user: User, auth: AuthContext, request: ChatAskRequest
    ) -> ChatAskResponse:
        question = request.question.strip() or request.question
        trace_id = request.request_id or str(uuid.uuid4())
        llm_provider = settings.effective_llm_provider
        llm_model_id = self._llm_model_id()
        prompt_version = GROUNDED_PROMPT_VERSION
        shadow_mode = settings.CHAT_VERIFICATION_SHADOW_MODE

        chat_session = await self._get_or_create_session(user=user, request=request)

        prior_before = await self.message_repo.list_by_session(
            chat_session.id, limit=_HISTORY_WINDOW
        )
        mem = chat_memory.normalize_memory(getattr(chat_session, 'memory_json', None))
        if request.clear_session_memory:
            mem = chat_memory.empty_memory()
        if request.memory_items_patch:
            chat_memory.apply_memory_item_patch(mem, request.memory_items_patch)
        if request.focus_lock_document_ids:
            mem['focus_lock_document_ids'] = [
                str(x) for x in request.focus_lock_document_ids
            ][:24]
        chat_memory.prune_expired_items(mem)
        chat_session.memory_json = dict(mem)
        await self._maybe_summarize_session(
            chat_session=chat_session, messages=prior_before, mem=mem
        )

        user_message = ChatMessage(
            session_id=chat_session.id, role='user', content=question
        )
        self._touch_session(chat_session)
        await self.message_repo.add(user_message, flush=True)
        await self.session.commit()
        await self.session.refresh(user_message)
        await self.session.refresh(chat_session)

        prior_orm_messages: list[ChatMessage] = [
            m for m in prior_before if m.id != user_message.id
        ]
        history: list[dict[str, str]] = [
            {'role': m.role, 'content': m.content} for m in prior_orm_messages
        ]

        preferred_document_ids = self._extract_preferred_document_ids(prior_orm_messages)
        preferred_chunk_refs = self._extract_preferred_chunk_refs(prior_orm_messages)
        requested_active_context_document_ids = self._parse_active_context_document_ids(
            request.active_context_document_ids
        )
        follow_up_document_ids = self._merge_document_ids(
            requested_active_context_document_ids,
            preferred_document_ids,
        )

        retrieval_query = question
        is_follow_up = False
        follow_up_plan: FollowUpClassification | None = None
        retrieval_settings_snapshot: dict[str, object] = {}
        verification_summary: dict[str, object] | None = None
        retrieval_error_type: str | None = None
        llm_error_type: str | None = None
        sources: list[ChatSource] = []
        document_results: list[ChatDocumentResult] = []
        active_context_document_ids = follow_up_document_ids
        filename_scoped_document_ids: list[UUID] = []
        filename_references: list[str] = []
        filename_scope_attempted = False
        answer = ''
        retrieval_debug_payload: dict[str, object] = {}
        memory_applied_payload: dict[str, object] = {
            'session_summary_present': bool(mem.get('session_summary')),
            'structured_items': len(mem.get('long_term_items') or []),
            'focus_lock_count': len(mem.get('focus_lock_document_ids') or []),
        }
        rerank_stats: dict[str, object] = {}
        candidate_sources_for_metrics: list[ChatSource] | None = None

        try:
            plan = await plan_retrieval_query(
                question=question,
                history=history,
                llm_client=self.llm_client,
            )
            retrieval_query = plan.retrieval_query
            is_follow_up = plan.is_follow_up
            follow_up_plan = plan.follow_up
        except Exception as exc:
            retrieval_error_type = type(exc).__name__
            logger.exception(
                'chat.retrieval_query_failed session=%s trace=%s',
                chat_session.id,
                trace_id,
            )
            answer = self._build_failure_answer(exc)
            verification_summary = {
                'result': 'retrieval_query_failed',
                'error_type': retrieval_error_type,
                'shadow_mode': shadow_mode,
                'trace_id': trace_id,
            }
            observability.record_rag_stage_error(stage='retrieval_query')
        else:
            retrieval_settings_snapshot = self._retrieval_settings_snapshot(
                request=request,
                retrieval_query=retrieval_query,
                is_follow_up=is_follow_up,
                follow_up=follow_up_plan,
            )
            if is_follow_up:
                logger.debug(
                    'Follow-up detected. Rewritten query: %r Preferred docs: %s',
                    retrieval_query,
                    preferred_document_ids,
                )

            if DocumentSearchService.is_document_discovery_query(retrieval_query):
                search_results = await DocumentSearchService(self.session).search(
                    query=retrieval_query,
                    auth=auth,
                    filters=request.retrieval_filters,
                    limit=settings.RAG_FINAL_TOP_N,
                )
                document_results = [
                    ChatDocumentResult.model_validate(result.as_dict())
                    for result in search_results
                ]
                if document_results:
                    active_context_document_ids = self._merge_document_ids(
                        [UUID(str(item.document_id)) for item in document_results],
                        follow_up_document_ids,
                    )
                    answer = self._build_document_search_answer(document_results)
                    verification_summary = {
                        'result': 'document_search',
                        'shadow_mode': shadow_mode,
                        'trace_id': trace_id,
                    }
                    retrieval_debug_payload = {
                        'document_search': {
                            'applied': True,
                            'result_count': len(document_results),
                        }
                    }
                    candidate_sources_for_metrics = []

            if not document_results:
                filename_references = DocumentSearchService.extract_file_references(
                    retrieval_query
                )
                if filename_references:
                    filename_scope_attempted = True
                    search_results = await DocumentSearchService(self.session).search(
                        query=" ".join(filename_references),
                        auth=auth,
                        filters=request.retrieval_filters,
                        limit=settings.RAG_FINAL_TOP_N,
                    )
                    filename_matches = [
                        result
                        for result in search_results
                        if DocumentSearchService.document_matches_file_reference(
                            result.document, filename_references
                        )
                    ]
                    filename_scoped_document_ids = [
                        UUID(str(result.document.id)) for result in filename_matches
                    ]
                    if filename_matches:
                        active_context_document_ids = self._merge_document_ids(
                            filename_scoped_document_ids,
                            follow_up_document_ids,
                        )
                        retrieval_debug_payload["filename_scope"] = {
                            "applied": True,
                            "references": filename_references,
                            "matched_documents": len(filename_scoped_document_ids),
                        }
                    else:
                        retrieval_debug_payload["filename_scope"] = {
                            "applied": False,
                            "references": filename_references,
                            "matched_documents": 0,
                        }

            explicit_document_ids = request.document_ids or None
            retrieval_document_ids = explicit_document_ids
            retrieval_preferred_document_ids = None
            lock_ids = self._parse_active_context_document_ids(
                [str(x) for x in (mem.get('focus_lock_document_ids') or [])]
            )
            if lock_ids and explicit_document_ids is None:
                retrieval_document_ids = lock_ids
            if (
                filename_scoped_document_ids
                and explicit_document_ids is None
                and not lock_ids
            ):
                retrieval_document_ids = filename_scoped_document_ids
            if (
                requested_active_context_document_ids
                and is_follow_up
                and explicit_document_ids is None
                and not lock_ids
                and not filename_scoped_document_ids
            ):
                retrieval_document_ids = requested_active_context_document_ids
            elif (
                follow_up_document_ids
                and is_follow_up
                and explicit_document_ids is None
                and not lock_ids
                and not filename_scoped_document_ids
            ):
                retrieval_preferred_document_ids = follow_up_document_ids

            try:
                if document_results:
                    retrieval = None
                elif filename_scope_attempted and not filename_scoped_document_ids:
                    retrieval = None
                    answer = self._build_no_sources_answer()
                    verification_summary = {
                        'result': 'filename_reference_not_found',
                        'filename_references': filename_references,
                        'shadow_mode': shadow_mode,
                        'trace_id': trace_id,
                    }
                else:
                    retrieval = await self.retrieval_service.retrieve(
                        question=retrieval_query,
                        auth=auth,
                        top_k=request.top_k,
                        document_ids=retrieval_document_ids,
                        preferred_document_ids=retrieval_preferred_document_ids,
                        filters=request.retrieval_filters,
                    )
            except Exception as exc:
                retrieval_error_type = type(exc).__name__
                logger.exception(
                    'chat.retrieval_failed session=%s trace=%s',
                    chat_session.id,
                    trace_id,
                )
                fallback_sources = (
                    await self._build_follow_up_neighbor_sources(
                        question=question,
                        preferred_chunk_refs=preferred_chunk_refs,
                    )
                    if is_follow_up and preferred_chunk_refs
                    else []
                )
                if fallback_sources:
                    sources = fallback_sources
                    candidate_sources_for_metrics = fallback_sources
                    active_context_document_ids = self._merge_document_ids(
                        self._extract_document_ids_from_sources(fallback_sources),
                        follow_up_document_ids,
                    )
                    retrieval_debug_payload = {
                        'fallback': 'last_cited_neighbor_chunks',
                        'retrieval_error_type': retrieval_error_type,
                    }
                    try:
                        memory_note = chat_memory.build_memory_prompt_block(mem)
                        prompt = build_grounded_prompt(
                            question=question,
                            sources=fallback_sources,
                            history=history if history else None,
                            memory_block=memory_note or None,
                            extra_rules=self._answer_style_rules(question),
                        )
                        raw_answer = (await self.llm_client.generate(prompt)).strip()
                    except Exception as llm_exc:
                        llm_error_type = type(llm_exc).__name__
                        sources = fallback_sources[:2]
                        answer = self._build_source_fallback_answer(sources)
                        verification_summary = {
                            'result': 'retrieval_failed_source_fallback',
                            'error_type': retrieval_error_type,
                            'llm_error_type': llm_error_type,
                            'shadow_mode': shadow_mode,
                            'trace_id': trace_id,
                        }
                    else:
                        if not raw_answer:
                            sources = fallback_sources[:2]
                            answer = self._build_source_fallback_answer(sources)
                            verification_summary = {
                                'result': 'retrieval_failed_source_fallback',
                                'error_type': retrieval_error_type,
                                'shadow_mode': shadow_mode,
                                'trace_id': trace_id,
                            }
                        else:
                            answer, sources, verification_summary = self._verify_and_normalize_answer(
                                question=question,
                                answer=raw_answer,
                                sources=fallback_sources,
                                shadow_mode=shadow_mode,
                                trace_id=trace_id,
                            )
                            verification_summary['retrieval_error_type'] = retrieval_error_type
                            verification_summary['retrieval_fallback'] = 'last_cited_neighbor_chunks'
                else:
                    answer = self._build_failure_answer(exc)
                    verification_summary = {
                        'result': 'retrieval_failed',
                        'error_type': retrieval_error_type,
                        'shadow_mode': shadow_mode,
                        'trace_id': trace_id,
                    }
                observability.record_rag_stage_error(stage='retrieval')
            else:
                if retrieval is None:
                    pass
                else:
                    previous_retrieval_debug = dict(retrieval_debug_payload)
                    retrieval_debug_payload = dict(
                        getattr(retrieval, 'retrieval_debug', {}) or {}
                    )
                    retrieval_debug_payload.update(previous_retrieval_debug)
                    candidate_sources = rerank_and_truncate_sources(
                        question,
                        self._prioritize_sources_for_question(
                            question=question,
                            sources=retrieval.sources,
                        ),
                        stats_out=rerank_stats,
                    )
                    if is_follow_up and preferred_chunk_refs:
                        candidate_sources = await self._augment_follow_up_sources_with_neighbors(
                            question=question,
                            sources=candidate_sources,
                            preferred_chunk_refs=preferred_chunk_refs,
                        )
                    candidate_sources = await self._augment_question_sources_from_same_documents(
                        question=question,
                        sources=candidate_sources,
                        max_sources=max(20, request.top_k * 3),
                    )
                    candidate_sources, constraint_debug = self._filter_sources_for_question_constraints(
                        question=question,
                        sources=candidate_sources,
                    )
                    if constraint_debug.get("time_filter_applied"):
                        retrieval_debug_payload["question_constraints"] = constraint_debug
                    candidate_sources_for_metrics = candidate_sources
                    grounded_document_ids = getattr(retrieval, 'grounded_document_ids', [])
                    active_context_document_ids = self._merge_document_ids(
                        list(grounded_document_ids),
                        self._extract_document_ids_from_sources(candidate_sources),
                        follow_up_document_ids,
                    )

                    if not candidate_sources:
                        answer = self._build_no_sources_answer()
                        sources = []
                        verification_summary = {
                            'result': 'no_sources',
                            'shadow_mode': shadow_mode,
                            'trace_id': trace_id,
                        }
                    else:
                        direct_answer = self._build_direct_answer(
                            question=question,
                            sources=candidate_sources,
                            trace_id=trace_id,
                        )
                        if direct_answer is not None:
                            answer, sources, verification_summary = direct_answer
                        else:
                            try:
                                memory_note = chat_memory.build_memory_prompt_block(mem)
                                prompt = build_grounded_prompt(
                                    question=question,
                                    sources=candidate_sources,
                                    history=history if history else None,
                                    memory_block=memory_note or None,
                                    extra_rules=self._answer_style_rules(question),
                                )
                                raw_answer = (await self.llm_client.generate(prompt)).strip()
                            except Exception as exc:
                                llm_error_type = type(exc).__name__
                                logger.exception(
                                    'chat.llm_failed session=%s trace=%s',
                                    chat_session.id,
                                    trace_id,
                                )
                                if isinstance(exc, httpx.TimeoutException):
                                    sources = candidate_sources[:2]
                                    answer = self._build_source_fallback_answer(sources)
                                    verification_summary = {
                                        'result': 'llm_timeout_source_fallback',
                                        'error_type': llm_error_type,
                                        'shadow_mode': shadow_mode,
                                        'trace_id': trace_id,
                                    }
                                else:
                                    answer = self._build_failure_answer(exc)
                                    sources = []
                                    verification_summary = {
                                        'result': 'llm_failed',
                                        'error_type': llm_error_type,
                                        'shadow_mode': shadow_mode,
                                        'trace_id': trace_id,
                                    }
                                observability.record_rag_stage_error(stage='llm')
                            else:
                                if not raw_answer:
                                    answer = self._build_empty_answer()
                                    sources = candidate_sources
                                    verification_summary = {
                                        'result': 'empty_llm',
                                        'shadow_mode': shadow_mode,
                                        'trace_id': trace_id,
                                    }
                                else:
                                    answer, sources, verification_summary = self._verify_and_normalize_answer(
                                        question=question,
                                        answer=raw_answer,
                                        sources=candidate_sources,
                                        shadow_mode=shadow_mode,
                                        trace_id=trace_id,
                                    )

        cited_document_ids = self._extract_document_ids_from_sources(sources)
        if cited_document_ids:
            active_context_document_ids = self._merge_document_ids(cited_document_ids, follow_up_document_ids)

        answer_confidence_value = self._compute_answer_confidence(sources, verification_summary)
        if verification_summary:
            observability.record_rag_verification(
                result=str(verification_summary.get('result')),
                shadow_mode=shadow_mode,
            )
            if shadow_mode and verification_summary.get('shadow_kept_raw'):
                observability.record_rag_shadow_override(reason='no_inline_citations')
            if shadow_mode and verification_summary.get('shadow_keeps_citation_answer'):
                observability.record_rag_shadow_override(reason='support_check_failed')
        if candidate_sources_for_metrics is not None:
            observability.record_rag_citation_filter(
                before_count=len(candidate_sources_for_metrics),
                after_count=len(sources),
            )
        if rerank_stats:
            observability.record_rag_rerank_event(
                order_changed=bool(rerank_stats.get('order_changed')),
                content_truncated_count=int(rerank_stats.get('sources_content_truncated') or 0),
            )
        observability.record_rag_low_confidence_answer(confidence=answer_confidence_value)

        model_label = f'{llm_provider}:{llm_model_id}'
        generation_metadata: dict[str, object] = {
            'trace_id': trace_id,
            'llm_provider': llm_provider,
            'llm_model_id': llm_model_id,
            'grounded_prompt_version': prompt_version,
            'retrieval': retrieval_settings_snapshot,
            'verification': verification_summary,
            'retrieval_debug': retrieval_debug_payload,
            'memory_applied': memory_applied_payload,
            'answer_confidence': answer_confidence_value,
        }
        if retrieval_error_type:
            generation_metadata['retrieval_error_type'] = retrieval_error_type
        if llm_error_type:
            generation_metadata['llm_error_type'] = llm_error_type

        chat_session.memory_json = dict(mem)

        assistant_message = ChatMessage(
            session_id=chat_session.id,
            role='assistant',
            content=answer,
            citations_json=([source.model_dump(mode='json') for source in sources] or None),
            model_name=model_label,
            generation_metadata_json=generation_metadata,
        )
        self._touch_session(chat_session)
        await self.message_repo.add(assistant_message, flush=True)
        await self.session.commit()
        await self.session.refresh(assistant_message)
        await self.session.refresh(chat_session)

        return ChatAskResponse(
            session_id=chat_session.id,
            answer=answer,
            answer_confidence=answer_confidence_value,
            sources=sources,
            document_results=document_results,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            parent_message_id=request.parent_message_id,
            request_id=request.request_id,
            cited_sources=sources,
            active_context_document_ids=[str(d) for d in active_context_document_ids],
            active_context_documents=self._build_active_context_documents(
                sources,
                active_context_document_ids,
            ),
            conversation_query=retrieval_query,
            generation_trace_id=trace_id,
            llm_provider=llm_provider,
            llm_model_id=llm_model_id,
            grounded_prompt_version=prompt_version,
            retrieval_settings=retrieval_settings_snapshot,
            verification=verification_summary,
            retrieval_debug=retrieval_debug_payload or None,
            memory_applied=memory_applied_payload,
        )
