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
from ..ai.llm_client import (
    LLMClientFactory,
    LLMClientProtocol,
    consume_generation_usage,
)
from ..ai.prompt_builder import GROUNDED_PROMPT_VERSION, build_grounded_prompt
from ..ai.ollama_llm_client import LLMTimeoutError
from ..rag.context_packer import pack_evidence_for_prompt
from ..rag import evidence_verifier as evidence_check
from ..rag.evidence_extractor import (
    EvidenceExtractor,
    EvidenceMatch,
    AMOUNT_CONTEXT_RE as _AMOUNT_CONTEXT_RE,
    MONEY_RE as _MONEY_RE,
    PIPE_RANGE_ROW_RE as _PIPE_RANGE_ROW_RE,
    YEAR_RANGE_RE as _YEAR_RANGE_RE,
)
from .query_writer import plan_retrieval_query
from .chat_completion import (
    ChatCompletion,
    document_ids_from_sources,
    finalize_chat_completion,
    merge_document_ids,
)
from .chat_scope_planner import (
    build_document_search_answer,
    parse_document_ids,
    plan_chat_scope,
)
from ..core import observability
from ..core.config import settings
from ..core.exceptions import AuthorizationError, NotFoundError
from ..core.security import AuthContext
from ..db.models import ChatMessage, ChatSession, DocumentChunk, User
from ..db.repo.chat import ChatMessageRepository, ChatSessionRepository
from ..db.repo.chunk_expansion import AuthorizedChunkExpansionRepository
from ..db.repo.document import DocumentChunkRepository
from ..schemas.chat_schema import (
    ChatAskRequest,
    ChatAskResponse,
    ChatDocumentResult,
    ChatMemoryPatchRequest,
    ChatSource,
)
from .audit_service import AuditService
from .retrieval_service import RetrievalService

logger = logging.getLogger(__name__)
_CITATION_RE = re.compile(r"\[(?:source\s*)?(\d+)\]", flags=re.IGNORECASE)
_AMOUNT_QUERY_RE = re.compile(
    r"\b(amount|total|balance|due|pay|payable|paid|cost|price|invoice|factuur|bill|charge)\b",
    flags=re.IGNORECASE,
)
_DUE_DATE_QUERY_RE = re.compile(
    r"\b(due date|deadline|payment date|pay before|pay by|te betalen voor|vervaldatum)\b|\bwhen\b.*\b(due|pay|payable)\b",
    flags=re.IGNORECASE,
)
_DATE_VALUE_RE = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b(?:19|20)\d{2}[/-]\d{1,2}[/-]\d{1,2}\b"
)
_DUE_DATE_CONTEXT_RE = re.compile(
    r"\b(due|deadline|payable|pay before|pay by|payment|te betalen voor|vervaldatum)\b",
    flags=re.IGNORECASE,
)
_TITLE_QUERY_RE = re.compile(
    r"\b(name|title|article|paper|publication|write|wrote|written|publish|published)\b",
    flags=re.IGNORECASE,
)
_SUMMARY_QUERY_RE = re.compile(
    r"\b(summarize|summarise|summary|overview|explain|describe)\b|\bwhat\b.{0,80}\babout\b",
    flags=re.IGNORECASE,
)
_INSUFFICIENT_MARKERS = (
    "could not verify",
    "could not find",
    "not enough",
    "insufficient",
    "do not have enough",
    "no indexed source",
    "no source",
)
_DEICTIC_FOLLOW_UP_RE = re.compile(
    r"\b(it|its|they|them|this|that|these|those|there|here|same)\b",
    flags=re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_START_WORK_QUERY_RE = re.compile(
    r"\bwhen\b.{0,50}\b(?:start|started|begin|began|join|joined)\b.{0,80}\b(?:work|working|role|job|position|employment|at)\b",
    flags=re.IGNORECASE,
)
_EMPLOYMENT_CONTEXT_RE = re.compile(
    r"\b(?:work|working|employment|experience|role|position|job|career|developer|engineer|"
    r"analyst|manager|consultant|assistant|lecturer|professor|researcher|specialist|architect)\b",
    flags=re.IGNORECASE,
)
_EDUCATION_ONLY_RE = re.compile(
    r"\b(?:education|student|degree|bachelor|master|phd|ph\.d|doctorate|thesis|diploma|university studies)\b",
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

_MONTH_YEAR_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(?:19|20)\d{2}\b",
    flags=re.IGNORECASE,
)


def _same_question_text(left: str, right: str) -> bool:
    def normalize(value: str) -> str:
        return re.sub(r"\W+", " ", value).strip().lower()

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
            user_id=user.id, title=request.question.strip()[:80] or "New chat"
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
            raise NotFoundError("Chat session not found")
        if existing.user_id != user.id:
            raise AuthorizationError("Chat session does not belong to this user")
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
        mem = chat_memory.normalize_memory(getattr(chat_session, "memory_json", None))
        if payload.clear:
            mem = chat_memory.empty_memory()
        if payload.items:
            chat_memory.apply_memory_item_patch(mem, payload.items)
        if payload.focus_lock_document_ids is not None:
            mem["focus_lock_document_ids"] = list(payload.focus_lock_document_ids)[:24]
        chat_memory.prune_expired_items(mem)
        chat_session.memory_json = dict(mem)
        self._touch_session(chat_session)
        await self.session.commit()
        return mem

    async def delete_session(self, session_id: str, actor: User) -> None:
        chat_session = await self._get_session_for_user(session_id, actor)
        await self.session_repo.delete(chat_session)
        await self.audit.log(
            action="chat.deleted",
            resource_type="chat_session",
            resource_id=str(chat_session.id),
            message="Chat session deleted",
            user=actor,
        )
        await self.session.commit()

    @staticmethod
    def _extract_preferred_document_ids(
        prior_messages_orm: list[ChatMessage],
    ) -> list[UUID]:
        for msg in reversed(prior_messages_orm):
            if msg.role != "assistant":
                continue
            citations = msg.citations_json
            if not citations:
                continue
            seen: set[str] = set()
            ids: list[UUID] = []
            for citation in citations:
                raw_id = citation.get("document_id")
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
            if msg.role != "assistant":
                continue
            citations = msg.citations_json or []
            refs: list[tuple[UUID, UUID]] = []
            seen: set[str] = set()
            for citation in citations:
                raw_chunk_id = citation.get("chunk_id")
                raw_document_id = citation.get("document_id")
                if not raw_chunk_id or not raw_document_id:
                    continue
                try:
                    chunk_id = UUID(str(raw_chunk_id))
                    document_id = UUID(str(raw_document_id))
                except ValueError:
                    continue
                key = f"{document_id}:{chunk_id}"
                if key in seen:
                    continue
                seen.add(key)
                refs.append((document_id, chunk_id))
            if refs:
                return refs
        return []

    @staticmethod
    def _looks_like_contextual_follow_up(question: str) -> bool:
        lowered = f" {question.lower()} "
        if any(
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
        ):
            return True
        return bool(_DEICTIC_FOLLOW_UP_RE.search(question))

    @staticmethod
    def _neighbor_offsets_for_question(question: str) -> list[int]:
        lowered = f" {question.lower()} "
        if any(
            marker in lowered
            for marker in (
                " after ",
                " next ",
                " then ",
                " later ",
                " following ",
                " subsequent ",
            )
        ):
            return [1, 2]
        if any(marker in lowered for marker in (" before ", " previous ", " prior ")):
            return [-1, -2]
        return [-1, 1]

    @staticmethod
    def _source_from_chunk(chunk: DocumentChunk, *, ranking_reason: str) -> ChatSource:
        document = chunk.document
        file_name = document.file_name if document is not None else ""
        file_path = document.file_path if document is not None else ""
        content = chunk.content or ""
        return ChatSource(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            file_name=file_name,
            file_path=file_path,
            page_number=chunk.page_number,
            section_title=chunk.section_title,
            heading_path=chunk.heading_path,
            snippet=build_snippet(content),
            # Expansion is structural, not a calibrated model score.
            score=0.0,
            distance=1.0,
            content=content,
            ranking_reason=ranking_reason,
        )

    async def _augment_follow_up_sources_with_neighbors(
        self,
        *,
        question: str,
        sources: list[ChatSource],
        preferred_chunk_refs: list[tuple[UUID, UUID]],
        auth: AuthContext,
        document_ids_scope: list[UUID] | None = None,
    ) -> list[ChatSource]:
        if (
            not sources
            or not preferred_chunk_refs
            or not self._looks_like_contextual_follow_up(question)
        ):
            return sources

        offsets = self._neighbor_offsets_for_question(question)
        by_doc_chunks = await AuthorizedChunkExpansionRepository(
            self.session
        ).list_grouped(
            document_ids=[document_id for document_id, _ in preferred_chunk_refs],
            auth=auth,
            document_ids_scope=document_ids_scope,
        )
        existing_ids = {str(source.chunk_id) for source in sources}
        neighbor_sources: list[ChatSource] = []

        for document_id, chunk_id in preferred_chunk_refs:
            doc_key = str(document_id)
            chunks = by_doc_chunks.get(doc_key, [])
            index_by_chunk_id = {str(chunk.id): idx for idx, chunk in enumerate(chunks)}
            anchor_index = index_by_chunk_id.get(str(chunk_id))
            if anchor_index is None:
                continue
            for offset in offsets:
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
                        ranking_reason="authorized_neighbor_expansion",
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
        auth: AuthContext,
        document_ids_scope: list[UUID] | None = None,
    ) -> list[ChatSource]:
        if not preferred_chunk_refs or not self._looks_like_contextual_follow_up(
            question
        ):
            return []

        offsets = self._neighbor_offsets_for_question(question)
        by_doc_chunks = await AuthorizedChunkExpansionRepository(
            self.session
        ).list_grouped(
            document_ids=[document_id for document_id, _ in preferred_chunk_refs],
            auth=auth,
            document_ids_scope=document_ids_scope,
        )
        sources: list[ChatSource] = []
        seen_chunk_ids: set[str] = set()

        for document_id, chunk_id in preferred_chunk_refs:
            doc_key = str(document_id)
            chunks = by_doc_chunks.get(doc_key, [])
            index_by_chunk_id = {str(chunk.id): idx for idx, chunk in enumerate(chunks)}
            anchor_index = index_by_chunk_id.get(str(chunk_id))
            if anchor_index is None:
                continue
            for offset in offsets:
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
                        ranking_reason="authorized_neighbor_fallback",
                    )
                )

        return sources

    async def _augment_question_sources_from_same_documents(
        self,
        *,
        question: str,
        sources: list[ChatSource],
        max_sources: int,
        auth: AuthContext,
        document_ids_scope: list[UUID] | None = None,
    ) -> list[ChatSource]:
        if not sources:
            return sources
        years = self._requested_years(question)
        query_terms = self._generic_query_terms(question)
        if not years and not query_terms:
            return sources

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

        by_doc_chunks = await AuthorizedChunkExpansionRepository(
            self.session
        ).list_grouped(
            document_ids=document_ids[:3],
            auth=auth,
            document_ids_scope=document_ids_scope,
        )
        boosted_sources: list[tuple[float, ChatSource]] = []
        for document_id in document_ids[:3]:
            chunks = by_doc_chunks.get(str(document_id), [])
            document_key = str(document_id)
            anchor_chunk_ids = source_chunk_ids_by_document.get(document_key, set())
            anchor_indexes = {
                chunk.chunk_index
                for chunk in chunks
                if str(chunk.id) in anchor_chunk_ids
            }
            for chunk in chunks:
                chunk_key = str(chunk.id)
                if chunk_key in existing_ids:
                    continue
                source = self._source_from_chunk(
                    chunk,
                    ranking_reason="authorized_same_document_expansion",
                )
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

    async def _augment_summary_sources_from_same_documents(
        self,
        *,
        question: str,
        sources: list[ChatSource],
        max_sources: int,
        auth: AuthContext,
        document_ids_scope: list[UUID] | None = None,
    ) -> list[ChatSource]:
        if not _SUMMARY_QUERY_RE.search(question) or not sources:
            return sources

        existing_by_id = {str(source.chunk_id): source for source in sources}
        document_ids: list[UUID] = []
        seen_documents: set[str] = set()
        for source in sources:
            document_key = str(source.document_id)
            if document_key in seen_documents:
                continue
            seen_documents.add(document_key)
            document_ids.append(UUID(document_key))

        by_doc_chunks = await AuthorizedChunkExpansionRepository(
            self.session
        ).list_grouped(
            document_ids=document_ids[:2],
            auth=auth,
            document_ids_scope=document_ids_scope,
        )
        body_sources: list[tuple[float, ChatSource]] = []
        seen_body_ids: set[str] = set()
        for document_id in document_ids[:2]:
            for chunk in by_doc_chunks.get(str(document_id), []):
                chunk_key = str(chunk.id)
                source = existing_by_id.get(chunk_key) or self._source_from_chunk(
                    chunk,
                    ranking_reason="authorized_summary_expansion",
                )
                relevance = self._summary_chunk_relevance(source=source, chunk=chunk)
                if relevance <= 0:
                    continue
                if chunk_key in seen_body_ids:
                    continue
                body_sources.append((relevance, source))
                seen_body_ids.add(chunk_key)

        if not body_sources:
            return sources
        body_sources.sort(key=lambda item: item[0], reverse=True)
        selected_sources = [source for _, source in body_sources[:max_sources]]
        selected_ids = {str(source.chunk_id) for source in selected_sources}
        return selected_sources + [
            source for source in sources if str(source.chunk_id) not in selected_ids
        ]

    async def _recheck_sources_authorized(
        self,
        *,
        sources: list[ChatSource],
        auth: AuthContext,
        document_ids_scope: list[UUID] | None = None,
    ) -> list[ChatSource]:
        if not sources:
            return sources
        visible = await DocumentChunkRepository(
            self.session
        ).filter_authorized_document_ids(
            document_ids=[source.document_id for source in sources],
            auth=auth,
            document_ids_scope=document_ids_scope,
        )
        return [source for source in sources if str(source.document_id) in visible]

    @classmethod
    def _employment_fingerprints(cls, source: ChatSource) -> set[tuple[str, str, str]]:
        text = "\n".join(
            [
                source.content or "",
                source.snippet or "",
                source.section_title or "",
            ]
        )
        fingerprints: set[tuple[str, str, str]] = set()
        document_key = str(source.document_id) if source.document_id else ""
        for line in text.splitlines():
            line_str = " ".join(line.split())
            if not line_str:
                continue
            for _label, _context, start, end in cls._employment_range_rows(line_str):
                start_year = cls._extract_year_token(start)
                end_year = cls._extract_year_token(end)
                if not start_year or not end_year:
                    continue
                fingerprints.add((document_key, start_year, end_year))
        return fingerprints

    @staticmethod
    def _extract_year_token(value: str) -> str:
        value_lower = value.lower().strip()
        if value_lower in {"present", "current", "now"}:
            return value_lower
        match = re.search(r"(19|20)\d{2}", value_lower)
        return match.group(0) if match else ""

    @classmethod
    def _dedupe_employment_sources(cls, sources: list[ChatSource]) -> list[ChatSource]:
        if len(sources) <= 1:
            return sources
        ordered = sorted(
            enumerate(sources), key=lambda pair: pair[1].score, reverse=True
        )
        accepted_fingerprints: set[tuple[str, str, str]] = set()
        kept_indexes: set[int] = set()
        for original_index, source in ordered:
            fingerprints = cls._employment_fingerprints(source)
            if not fingerprints:
                kept_indexes.add(original_index)
                continue
            if fingerprints & accepted_fingerprints:
                continue
            accepted_fingerprints |= fingerprints
            kept_indexes.add(original_index)
        return [source for index, source in enumerate(sources) if index in kept_indexes]

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
            nearest = (
                min(
                    abs(chunk.chunk_index - anchor)
                    for anchor in anchor_indexes
                    if anchor >= 0
                )
                if any(anchor >= 0 for anchor in anchor_indexes)
                else None
            )
            if nearest is not None and nearest <= 16:
                score += max(0.2, 2.0 / (nearest + 1))
        return score

    @staticmethod
    def _summary_chunk_relevance(*, source: ChatSource, chunk: DocumentChunk) -> float:
        text = " ".join(
            [
                chunk.content or "",
                chunk.section_title or "",
                chunk.heading_path or "",
            ]
        ).lower()
        words = re.findall(r"\b\w+\b", text)
        if len(words) < 25:
            return 0.0

        section = " ".join(
            [
                source.section_title or "",
                source.heading_path or "",
            ]
        ).lower()
        score = min(2.0, len(words) / 160)
        if re.search(r"\babstract\b", section):
            score += 5.0
        if re.search(r"\b(introduction|background)\b", section):
            score += 3.0
        if re.search(r"\b(results?|findings?|discussion|conclusion)\b", section):
            score += 3.0
        if re.search(r"\bthis paper analy[sz]es\b", text):
            score += 5.0
        if re.search(r"\bresults showed\b", text):
            score += 4.0
        if re.search(r"\bimports? and exports?\b", text):
            score += 3.0
        if re.search(r"\bforeign trade positively\b", text):
            score += 3.0
        chunk_index = getattr(chunk, "chunk_index", None)
        if isinstance(chunk_index, int) and chunk_index >= 0:
            score += max(0.2, 1.5 / (chunk_index + 1))
        return score

    @staticmethod
    def _parse_active_context_document_ids(
        document_ids: list[str] | None,
    ) -> list[UUID]:
        return parse_document_ids(document_ids)

    @staticmethod
    def _build_no_sources_answer() -> str:
        return (
            "I could not find indexed source material for that question. "
            "The relevant file may not be synced yet, may not have been chunked and embedded, "
            "or you may not have access to it."
        )

    @staticmethod
    def _build_document_search_answer(
        results: list[ChatDocumentResult],
        *,
        total: int | None = None,
    ) -> str:
        return build_document_search_answer(results, total=total)

    @staticmethod
    def _build_empty_answer() -> str:
        return (
            "I could not produce an answer because the language model returned an empty response. "
            "Your question was saved in the chat history."
        )

    @staticmethod
    def _extract_upstream_error_detail(exc: httpx.HTTPStatusError) -> str:
        detail: str | None = None
        try:
            payload = exc.response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            for key in ("error", "detail", "message"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    detail = value.strip()
                    break

        if detail is None:
            response_text = exc.response.text.strip()
            if response_text:
                detail = response_text

        if detail is None:
            detail = f"HTTP {exc.response.status_code}"

        return " ".join(detail.split())

    def _build_failure_answer(self, exc: Exception) -> str:
        if isinstance(exc, httpx.TimeoutException):
            return (
                "I could not answer because the embedding or language model request timed out. "
                "Your question was saved in the chat history."
            )
        if isinstance(exc, httpx.HTTPStatusError):
            detail = self._extract_upstream_error_detail(exc)
            return (
                "I could not answer because the AI backend returned an error: "
                f"{detail}. Your question was saved in the chat history."
            )
        if isinstance(exc, httpx.RequestError):
            return (
                "I could not answer because the embedding or language model service was unreachable. "
                "Your question was saved in the chat history."
            )
        return (
            "I could not answer because the retrieval or generation pipeline failed. "
            "Your question was saved in the chat history."
        )

    @staticmethod
    def _filter_sources_to_citations(
        answer: str, sources: list[ChatSource]
    ) -> tuple[str, list[ChatSource]]:
        return evidence_check.filter_sources_to_citations(answer, sources)

    @staticmethod
    def _answer_style_rules(question: str) -> list[str]:
        rules: list[str] = []
        if _SUMMARY_QUERY_RE.search(question):
            rules.extend(
                [
                    "For summarize, summary, overview, explain, or describe questions: summarize the source content itself; do not answer by only naming the title, author, or publication date.",
                    "Write a concise 2-4 sentence summary covering the article's subject, scope, and main supported points.",
                    "If the retrieved sources only identify title/metadata and do not provide article substance, say there is not enough indexed source content to summarize it.",
                ]
            )
        if _AMOUNT_QUERY_RE.search(question):
            rules.extend(
                [
                    "For amount, total, balance, payable, invoice, bill, cost, or price questions: answer with the exact amount first.",
                    "Prefer the payable/total/invoice amount over tariffs, rates, fees, background, or explanatory text unless the user asks for those.",
                    "Keep amount answers to one short sentence when one amount directly answers the question.",
                ]
            )
        if _EMPLOYMENT_CONTEXT_RE.search(question):
            rules.extend(
                [
                    "For work history questions, output one bullet per distinct employer-and-date-range; never repeat the same employer with the same dates on separate bullets.",
                    "When the same employer and date range appear across multiple sources, merge them into a single bullet and attach every supporting citation (e.g. [1][3]).",
                    "Format each bullet as 'Employer (Location, Start - End) [citations]'. Do not echo raw pipe-delimited fragments or duplicate the employer string within a bullet.",
                    "Only include employment entries whose date range overlaps the period the question asks about.",
                ]
            )
        return rules

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
    def _build_direct_answer(
        cls, *, question: str, sources: list[ChatSource], trace_id: str
    ) -> tuple[str, list[ChatSource], dict[str, object]] | None:
        summary_answer = cls._build_extractive_summary_answer(
            question=question, sources=sources
        )
        if summary_answer is not None:
            answer, cited_sources = summary_answer
            return (
                answer,
                cited_sources,
                {
                    "result": "direct_extraction",
                    "direct_extraction_type": "summary",
                    "trace_id": trace_id,
                    "shadow_mode": False,
                },
            )

        title_answer = cls._build_direct_title_answer(
            question=question, sources=sources
        )
        if title_answer is not None:
            answer, cited_sources = title_answer
            return (
                answer,
                cited_sources,
                {
                    "result": "direct_extraction",
                    "direct_extraction_type": "title",
                    "trace_id": trace_id,
                    "shadow_mode": False,
                },
            )

        due_date_answer = cls._build_direct_due_date_answer(
            question=question, sources=sources
        )
        if due_date_answer is not None:
            answer, cited_sources = due_date_answer
            return (
                answer,
                cited_sources,
                {
                    "result": "direct_extraction",
                    "direct_extraction_type": "due_date",
                    "trace_id": trace_id,
                    "shadow_mode": False,
                },
            )

        amount_answer = cls._build_direct_amount_answer(
            question=question, sources=sources
        )
        if amount_answer is not None:
            answer, cited_sources = amount_answer
            return (
                answer,
                cited_sources,
                {
                    "result": "direct_extraction",
                    "direct_extraction_type": "amount",
                    "trace_id": trace_id,
                    "shadow_mode": False,
                },
            )

        employment_start_answer = cls._build_direct_employment_start_answer(
            question=question, sources=sources
        )
        if employment_start_answer is not None:
            answer, cited_sources = employment_start_answer
            return (
                answer,
                cited_sources,
                {
                    "result": "direct_extraction",
                    "direct_extraction_type": "employment_start",
                    "trace_id": trace_id,
                    "shadow_mode": False,
                },
            )

        range_answer = cls._build_direct_range_answer(
            question=question, sources=sources
        )
        if range_answer is not None:
            answer, cited_sources = range_answer
            return (
                answer,
                cited_sources,
                {
                    "result": "direct_extraction",
                    "direct_extraction_type": "date_range_rows",
                    "trace_id": trace_id,
                    "shadow_mode": False,
                },
            )
        return None

    @classmethod
    def _build_direct_due_date_answer(
        cls, *, question: str, sources: list[ChatSource]
    ) -> tuple[str, list[ChatSource]] | None:
        if not _DUE_DATE_QUERY_RE.search(question):
            return None
        entity_terms = cls._direct_answer_entity_terms(question)
        matches = EvidenceExtractor.entity_proximity_extractor(
            sources,
            entity_terms=entity_terms
            or ["due", "deadline", "payment", "payable", "vervaldatum"],
            value_pattern=_DATE_VALUE_RE,
            context_window=120,
        )
        matches = [m for m in matches if _DUE_DATE_CONTEXT_RE.search(m.context)]
        if not matches:
            return None
        best = max(matches, key=lambda item: item.score)
        return f"{best.value} [1]", [best.source]

    @classmethod
    def _build_direct_title_answer(
        cls, *, question: str, sources: list[ChatSource]
    ) -> tuple[str, list[ChatSource]] | None:
        if _SUMMARY_QUERY_RE.search(question):
            return None
        if not _TITLE_QUERY_RE.search(question):
            return None
        years = cls._requested_years(question)
        best: tuple[float, str, ChatSource] | None = None
        for source in sources:
            if years and not cls._source_supports_years(source, years):
                continue
            evidence = cls._source_evidence_text(source)
            if not cls._source_can_answer_title_query(source, evidence):
                continue
            title = cls._title_from_source(source)
            if title is None:
                continue
            score = source.score
            if years:
                score += 3.0
            if re.search(
                r"\b(article|paper|journal|publication)\b",
                evidence,
                flags=re.IGNORECASE,
            ):
                score += 2.0
            candidate = (score, title, source)
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is None:
            return None
        _score, title, source = best
        return f"{title} [1]", [source]

    @staticmethod
    def _source_can_answer_title_query(source: ChatSource, evidence: str) -> bool:
        file_hint = f"{source.file_name or ''} {source.file_path or ''}".lower()
        if re.search(
            r"(^|[^a-z0-9])(cv|resume|curriculum[-_\s]*vitae)([^a-z0-9]|$)", file_hint
        ):
            return False
        return bool(
            re.search(
                r"\b(article|paper|journal|publication|published|doi|abstract)\b",
                evidence,
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _title_from_source(source: ChatSource) -> str | None:
        candidates = [
            source.file_name or "",
            source.heading_path or "",
            source.section_title or "",
        ]
        for candidate in candidates:
            value = candidate.strip()
            if not value:
                continue
            if "/" in value:
                value = value.split("/")[-1].strip()
            value = re.sub(
                r"\.(pdf|docx?|odt|txt|md)$", "", value, flags=re.IGNORECASE
            ).strip()
            value = re.split(r"\s*>\s*", value)[0].strip()
            value = re.sub(r"\s*-\s+", ": ", value).strip(" :-")
            if len(value) >= 8 and value.lower() not in {"introduction", "appendix"}:
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
        matches = EvidenceExtractor.amount_extractor(
            sources, entity_terms=cls._direct_answer_entity_terms(question)
        )
        if not matches:
            return None
        best = matches[0]
        return f"{best.value} [1]", [best.source]

    @classmethod
    def _build_direct_range_answer(
        cls, *, question: str, sources: list[ChatSource]
    ) -> tuple[str, list[ChatSource]] | None:
        years = cls._requested_years(question)
        if len(years) < 2:
            return None
        query_start, query_end = min(years), max(years)
        rows_by_key: dict[
            tuple[str, int, int], tuple[str, str, str, ChatSource, int, int, int]
        ] = {}
        for match in EvidenceExtractor.date_range_extractor(sources):
            if not cls._looks_like_clean_range_label(match.label):
                continue
            if match.context and not cls._looks_like_clean_range_label(
                match.context, allow_short=True
            ):
                continue
            start_year = cls._first_year(match.start)
            end_year = cls._first_year(match.end) or 9999
            if start_year is None:
                continue
            if end_year < query_start or start_year > query_end:
                continue
            label_clean = cls._strip_pipe_artifacts(match.label)
            context_clean = cls._strip_pipe_artifacts(match.context)
            value_clean = match.value.strip()
            label_token = re.sub(r"[^a-z0-9]+", "", label_clean.lower())
            if not label_token:
                continue
            key = (label_token, start_year, end_year)
            specificity = cls._range_value_specificity(value_clean)
            existing = rows_by_key.get(key)
            if existing is not None and specificity <= existing[6]:
                continue
            rows_by_key[key] = (
                label_clean,
                context_clean,
                value_clean,
                match.source,
                start_year,
                end_year,
                specificity,
            )
        if not rows_by_key:
            return None
        rows = sorted(
            rows_by_key.values(), key=lambda item: (item[4], item[5], item[0].lower())
        )[:6]
        cited_sources = [row[3] for row in rows]
        lines = [
            f"- {label} ({context}, {date_range}) [{index}]"
            if context
            else f"- {label} ({date_range}) [{index}]"
            for index, (
                label,
                context,
                date_range,
                _source,
                _start,
                _end,
                _spec,
            ) in enumerate(rows, start=1)
        ]
        return "\n".join(lines), cited_sources

    @staticmethod
    def _strip_pipe_artifacts(text: str) -> str:
        if not text:
            return ""
        cleaned = re.split(r"\s*\|\s*", text)[0]
        return " ".join(cleaned.split()).strip(" -:,;")

    @staticmethod
    def _range_value_specificity(value: str) -> int:
        if not value:
            return 0
        score = 0
        if re.search(r"[A-Za-z]{3,}", value):
            score += 2
        if re.search(r"\d{4}", value):
            score += 1
        return score

    @classmethod
    def _build_direct_employment_start_answer(
        cls, *, question: str, sources: list[ChatSource]
    ) -> tuple[str, list[ChatSource]] | None:
        if not _START_WORK_QUERY_RE.search(question):
            return None
        entity_terms = [
            term
            for term in cls._direct_answer_entity_terms(question)
            if term
            not in {
                "start",
                "started",
                "begin",
                "began",
                "join",
                "joined",
                "work",
                "working",
                "role",
                "job",
                "position",
                "employment",
            }
        ]
        subject = cls._employment_subject(question)

        best_range: EvidenceMatch | None = None
        for match in EvidenceExtractor.date_range_extractor(sources):
            combined = f"{match.label} {match.context} {match.source.section_title or ''} {match.source.heading_path or ''}"
            entity_score = EvidenceExtractor.entity_match_score(entity_terms, combined)
            if entity_terms and entity_score <= 0:
                continue
            if not cls._looks_like_employment_row(combined):
                continue
            score = match.score + entity_score * 4.0
            if _EMPLOYMENT_CONTEXT_RE.search(combined):
                score += 2.0
            if match.source.file_name and re.search(
                r"(^|[^a-z0-9])(cv|resume|curriculum[-_\s]*vitae)([^a-z0-9]|$)",
                match.source.file_name,
                re.I,
            ):
                score += 1.0
            candidate = EvidenceMatch(
                kind=match.kind,
                value=match.value,
                source=match.source,
                score=score,
                label=match.label,
                context=match.context,
                start=match.start,
                end=match.end,
            )
            if best_range is None or candidate.score > best_range.score:
                best_range = candidate

        if best_range is not None:
            target = cls._employment_target(
                best_range.label, best_range.context, entity_terms
            )
            if best_range.end:
                return (
                    f"{subject} started working at {target} in {best_range.start} "
                    f"(listed range: {best_range.start} - {best_range.end}) [1]",
                    [best_range.source],
                )
            return f"{subject} started working at {target} in {best_range.start} [1]", [
                best_range.source
            ]

        # Generic fallback for free-text CV/resume prose, e.g.
        # "Selahaddin Eyyubi University ... Software Developer ... started in 2021".
        date_pattern = re.compile(
            rf"(?:{_MONTH_YEAR_RE.pattern})|(?:{_YEAR_RE.pattern})",
            flags=re.IGNORECASE,
        )
        proximity_matches = EvidenceExtractor.entity_proximity_extractor(
            sources,
            entity_terms=entity_terms,
            value_pattern=date_pattern,
            context_window=220,
            require_start_marker=True,
        )
        proximity_matches = [
            match
            for match in proximity_matches
            if cls._looks_like_employment_row(match.context)
        ]
        if proximity_matches:
            best = proximity_matches[0]
            target = cls._employment_target(best.context, "", entity_terms)
            return f"{subject} started working at {target} in {best.value} [1]", [
                best.source
            ]

        return None

    @staticmethod
    def _employment_range_rows(line: str) -> list[tuple[str, str, str, str]]:
        rows: list[tuple[str, str, str, str]] = []
        for match in _PIPE_RANGE_ROW_RE.finditer(line):
            rows.append(
                (
                    " ".join(match.group("label").split()).strip(":- "),
                    " ".join(match.group("context").split()).strip(":- "),
                    match.group("start").strip(),
                    match.group("end").strip(),
                )
            )
        for match in _YEAR_RANGE_RE.finditer(line):
            start = match.group(1).strip()
            end = match.group(2).strip()
            context_start = max(0, match.start() - 120)
            context_end = min(len(line), match.end() + 120)
            context = " ".join(line[context_start:context_end].split()).strip(":- ")
            rows.append((context, "", start, end))
        return rows

    @staticmethod
    def _looks_like_employment_row(text: str) -> bool:
        if not text.strip():
            return False
        has_work_signal = bool(_EMPLOYMENT_CONTEXT_RE.search(text))
        education_only = bool(_EDUCATION_ONLY_RE.search(text)) and not has_work_signal
        return has_work_signal and not education_only

    @staticmethod
    def _employment_target(label: str, context: str, entity_terms: list[str]) -> str:
        candidates = [label, context]
        compact_terms = [
            re.sub(r"[^a-z0-9]+", "", term.lower()) for term in entity_terms
        ]
        for candidate in candidates:
            compact_candidate = re.sub(r"[^a-z0-9]+", "", candidate.lower())
            if any(term and term in compact_candidate for term in compact_terms):
                return candidate
        return label or context or "the organization"

    @staticmethod
    def _employment_subject(question: str) -> str:
        for term in re.findall(r"[A-ZÖÜĞŞİÇ][A-Za-zÖÜĞŞİÇöüğşıç'-]{2,}", question):
            if term.lower() not in {"when"}:
                return term
        for term in re.findall(r"[a-zöüğşıç'-]{4,}", question.lower()):
            if term not in _GENERIC_QUERY_STOPWORDS and term not in {
                "started",
                "start",
                "work",
                "working",
            }:
                return term.capitalize()
        return "They"

    @classmethod
    def _direct_answer_entity_terms(cls, question: str) -> list[str]:
        return [
            term
            for term in cls._generic_query_terms(question)
            if term not in _AMOUNT_QUERY_TERMS
        ]

    @staticmethod
    def _looks_like_clean_range_label(value: str, *, allow_short: bool = False) -> bool:
        cleaned = value.strip()
        if len(cleaned) < (2 if allow_short else 3) or len(cleaned) > 90:
            return False
        if any(
            marker in cleaned
            for marker in (
                "●",
                "Context above",
                "Context below",
                "Extracted table facts",
            )
        ):
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

    @classmethod
    def _looks_like_title_only_summary_answer(
        cls, *, question: str, answer: str, sources: list[ChatSource]
    ) -> bool:
        if not _SUMMARY_QUERY_RE.search(question):
            return False
        plain = _CITATION_RE.sub("", answer).strip()
        words = re.findall(r"\b\w+\b", plain)
        if len(words) > 35:
            return False
        lowered = plain.lower()
        title_like = re.search(
            r"\b(article|paper|publication)\b.{0,100}\b(is|was|titled|called|named|written)\b",
            lowered,
            flags=re.IGNORECASE,
        )
        source_titles = [
            title.lower()
            for title in (cls._title_from_source(source) for source in sources)
            if title
        ]
        if title_like and any(title in lowered for title in source_titles):
            return True
        return bool(
            source_titles
            and any(title in lowered for title in source_titles)
            and re.search(r'["“”]', plain)
            and len(re.findall(r"[.!?]+", plain)) <= 1
        )

    @staticmethod
    def _clean_summary_sentence(sentence: str) -> str:
        cleaned = " ".join(sentence.split()).strip(" -:")
        starters = (
            "this paper",
            "this article",
            "this study",
            "the paper",
            "the article",
            "the study",
            "results of",
            "the results",
            "furthermore",
            "imports",
            "exports",
            "production",
            "foreign trade",
        )
        lowered = cleaned.lower()
        positions = [
            lowered.find(starter)
            for starter in starters
            if 0 <= lowered.find(starter) <= 220
        ]
        if positions:
            cleaned = cleaned[min(positions) :].strip(" -:")
        cleaned = re.sub(r"^[^.!?]{0,120}\s>\s", "", cleaned).strip(" -:")
        return cleaned

    @classmethod
    def _build_extractive_summary_answer(
        cls, *, question: str, sources: list[ChatSource]
    ) -> tuple[str, list[ChatSource]] | None:
        if not _SUMMARY_QUERY_RE.search(question):
            return None

        candidates: list[tuple[float, int, str, ChatSource]] = []
        seen_sentences: set[str] = set()
        for source_order, source in enumerate(sources):
            text = " ".join((source.content or source.snippet or "").split())
            if len(text) < 120:
                continue
            section = (
                f"{source.section_title or ''} {source.heading_path or ''}".lower()
            )
            for raw_sentence in re.split(r"(?<=[.!?])\s+", text):
                sentence = cls._clean_summary_sentence(raw_sentence)
                words = re.findall(r"\b\w+\b", sentence)
                if len(words) < 10 or len(words) > 55:
                    continue
                if not re.match(r"[A-Z]", sentence):
                    continue
                sentence_lower = sentence.lower()
                if "this paper" in sentence_lower and not sentence_lower.startswith(
                    "this paper"
                ):
                    continue
                if "this article" in sentence_lower and not sentence_lower.startswith(
                    "this article"
                ):
                    continue
                if (
                    cls._title_from_source(source)
                    and cls._title_from_source(source).lower() in sentence_lower
                ):
                    continue
                score = 0.0
                if re.search(
                    r"\b(this paper|this article|study|analy[sz]es|examines)\b",
                    sentence_lower,
                ):
                    score += 4.0
                if re.search(
                    r"\b(result|show|find|impact|effect|significant)\b", sentence_lower
                ):
                    score += 3.0
                if re.search(
                    r"\b(imports?|exports?|foreign trade|labor market|employment|wages?)\b",
                    sentence_lower,
                ):
                    score += 2.0
                if re.search(r"\babstract\b", section):
                    score += 2.0
                if re.search(
                    r"\b(results?|findings?|discussion|conclusion)\b", section
                ):
                    score += 1.5
                score += max(0.0, 2.0 - (source_order * 0.25))
                if score <= 0:
                    continue
                normalized = re.sub(r"\W+", " ", sentence_lower).strip()
                if normalized in seen_sentences:
                    continue
                seen_sentences.add(normalized)
                candidates.append((score, source_order, sentence, source))

        if not candidates:
            return None

        selected: list[tuple[str, ChatSource]] = []
        selected_source_ids: set[str] = set()
        method_candidates = [
            item
            for item in candidates
            if item[2].lower().startswith("this paper analy")
        ]
        ordered_candidates = [
            *sorted(method_candidates, key=lambda item: (item[1], -item[0]))[:1],
            *[
                item
                for item in sorted(candidates, key=lambda item: (item[1], -item[0]))
                if item not in method_candidates
            ],
        ]
        for _score, _source_order, sentence, source in ordered_candidates:
            source_key = str(source.chunk_id)
            if source_key in selected_source_ids and len(selected_source_ids) >= 2:
                continue
            selected.append((sentence, source))
            selected_source_ids.add(source_key)
            if len(selected) >= 3:
                break

        if not selected:
            return None

        supporting_sources: list[ChatSource] = []
        source_indexes: dict[str, int] = {}
        answer_parts: list[str] = []
        for sentence, source in selected:
            source_key = str(source.chunk_id)
            if source_key not in source_indexes:
                supporting_sources.append(source)
                source_indexes[source_key] = len(supporting_sources)
            answer_parts.append(f"{sentence} [{source_indexes[source_key]}]")

        return " ".join(answer_parts), supporting_sources

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
            if (
                _same_question_text(possible_question, cleaned_question)
                and possible_answer
            ):
                return possible_answer

        candidates = {
            cleaned_question,
            cleaned_question.rstrip(" ?!.:："),
        }
        for candidate in sorted(candidates, key=len, reverse=True):
            if not candidate:
                continue
            if cleaned_answer.lower().startswith(candidate.lower()):
                remainder = cleaned_answer[len(candidate) :].strip()
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
        challenge_terms = (
            " not ",
            " never ",
            " wrong ",
            " incorrect ",
            " are you sure ",
            " he never ",
            " she never ",
        )
        return any(term in lowered for term in challenge_terms)

    @staticmethod
    def _source_texts(sources: list[ChatSource]) -> list[str]:
        texts: list[str] = []
        for source in sources:
            source_text = (source.content or source.snippet or "").strip()
            if source_text:
                texts.append(f" {source_text.lower()} ")
        return texts

    _EVIDENCE_STOPWORDS = frozenset(
        {
            "a",
            "an",
            "the",
            "is",
            "are",
            "was",
            "were",
            "be",
            "to",
            "of",
            "in",
            "on",
            "for",
            "and",
            "or",
            "at",
            "by",
            "from",
            "with",
            "that",
            "this",
            "it",
            "as",
            "i",
            "we",
            "you",
            "they",
            "have",
            "has",
            "had",
            "not",
            "no",
            "yes",
            "can",
            "could",
            "would",
            "should",
            "will",
            "may",
            "might",
            "do",
            "does",
            "did",
            "about",
            "into",
            "than",
            "then",
            "there",
            "their",
            "total",
            "amount",
            "served",
        }
    )

    @classmethod
    def _evidence_terms(cls, text: str) -> set[str]:
        tokens = {
            token.lower()
            for token in re.findall(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*", text.lower())
            if token
        }
        return {
            token
            for token in tokens
            if len(token) >= 3 and token not in cls._EVIDENCE_STOPWORDS
        }

    @classmethod
    def _extract_claim_markers(cls, text: str) -> set[str]:
        """Amounts/IDs that must appear in supporting sources when present in the answer."""
        markers: set[str] = set()
        lowered = text.lower()
        for match in re.finditer(
            r"\b(?:eur|usd|gbp|\$|€)\s*[\d][\d.,]*|\b[\d][\d.,]*\s*(?:eur|usd|gbp)\b",
            lowered,
        ):
            markers.add(re.sub(r"\s+", "", match.group(0)))
        for match in re.finditer(r"\b(?:inv|invoice)[- ]?[a-z0-9\-./]+\b", lowered):
            markers.add(re.sub(r"\s+", "", match.group(0)))
        for match in re.finditer(r"\b\d{4,}\b", lowered):
            markers.add(match.group(0))
        return markers

    @classmethod
    def _source_supports_answer_text(cls, *, answer: str, source: ChatSource) -> bool:
        source_text = f" {(source.content or source.snippet or '').lower()} "
        if not source_text.strip():
            return False
        markers = cls._extract_claim_markers(answer)
        if markers:
            compact_source = re.sub(r"\s+", "", source_text)
            if not any(
                marker in compact_source or marker in source_text for marker in markers
            ):
                return False
        answer_terms = cls._evidence_terms(answer)
        if not answer_terms:
            return False
        source_terms = cls._evidence_terms(source_text)
        if not source_terms:
            return False
        overlap = answer_terms & source_terms
        # Require meaningful overlap; a lunch menu must not support an invoice total.
        min_hits = 1 if markers else max(2, (len(answer_terms) + 2) // 3)
        return len(overlap) >= min_hits

    def _answer_is_supported(
        self,
        *,
        question: str,
        answer: str,
        cited_sources: list[ChatSource],
    ) -> bool:
        ok, _checks = evidence_check.answer_is_supported(
            question=question, answer=answer, cited_sources=cited_sources
        )
        return ok

    @classmethod
    def _select_supporting_sources(
        cls,
        *,
        question: str,
        answer: str,
        sources: list[ChatSource],
        max_sources: int = 2,
    ) -> list[ChatSource]:
        return evidence_check.select_supporting_sources(
            question=question,
            answer=answer,
            sources=sources,
            max_sources=max_sources,
        )

    @staticmethod
    def _requested_years(question: str) -> list[int]:
        return evidence_check.requested_years(question)

    @staticmethod
    def _source_supports_years(source: ChatSource, years: list[int]) -> bool:
        return evidence_check.source_supports_years(source, years)

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

    @staticmethod
    def _append_citations(answer: str, count: int) -> str:
        return evidence_check.append_citations(answer, count)

    @staticmethod
    def _build_source_fallback_answer(
        sources: list[ChatSource], *, mode: str = "extractive_llm_outage"
    ) -> tuple[str, list[ChatSource], str]:
        return evidence_check.build_extractive_fallback(sources, mode=mode)

    def _build_unverified_answer(self, question: str) -> str:
        return evidence_check.unverified_answer(question)

    def _llm_model_id(self) -> str:
        client = self.llm_client
        model = getattr(client, "model", None)
        if model is not None:
            return str(model)
        return "stub"

    @staticmethod
    def _empty_llm_usage() -> dict[str, object]:
        return {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost": 0.0,
            "fallback_used": False,
            "cache_hits": 0,
        }

    def _record_llm_usage(self, usage_totals: dict[str, object]) -> None:
        usage = consume_generation_usage()
        if not isinstance(usage, dict):
            usage = getattr(self.llm_client, "last_usage", None)
        if not isinstance(usage, dict):
            return

        usage_totals["calls"] = int(usage_totals.get("calls", 0)) + 1
        usage_totals["input_tokens"] = int(usage_totals.get("input_tokens", 0)) + int(
            usage.get("input_tokens", 0) or 0
        )
        usage_totals["output_tokens"] = int(usage_totals.get("output_tokens", 0)) + int(
            usage.get("output_tokens", 0) or 0
        )
        usage_totals["total_tokens"] = int(usage_totals.get("total_tokens", 0)) + int(
            usage.get("total_tokens", 0) or 0
        )
        usage_totals["estimated_cost"] = round(
            float(usage_totals.get("estimated_cost", 0.0))
            + float(usage.get("estimated_cost", 0.0) or 0.0),
            8,
        )
        if bool(usage.get("fallback_used")):
            usage_totals["fallback_used"] = True
        if bool(usage.get("cached")):
            usage_totals["cache_hits"] = int(usage_totals.get("cache_hits", 0)) + 1
        err = usage.get("primary_error_type")
        if err:
            usage_totals["last_error_type"] = str(err)

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
            filters_dump = request.retrieval_filters.model_dump(mode="json")
        snap: dict[str, object] = {
            "top_k": request.top_k,
            "document_ids": [str(d) for d in (request.document_ids or [])],
            "retrieval_filters": filters_dump,
            "active_context_document_ids": list(
                request.active_context_document_ids or []
            ),
            "is_follow_up": is_follow_up,
            "retrieval_query": retrieval_query,
        }
        if follow_up is not None:
            snap["follow_up_confidence"] = follow_up.confidence
            snap["follow_up_reasons"] = list(follow_up.reasons)
        return snap

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
        lines = [f"{m.role}: {m.content[:520]}" for m in head]
        prompt = (
            "Summarize durable facts and unresolved threads from this chat prefix "
            "in 4-6 sentences for future turns. Do not invent facts.\n\n"
            + "\n".join(lines)
        )
        try:
            summary = (await self.llm_client.generate(prompt)).strip()
            if summary:
                mem["session_summary"] = summary[:4000]
                chat_session.memory_json = dict(mem)
        except Exception:
            logger.exception("chat.session_summary_failed session=%s", chat_session.id)

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
            "shadow_mode": shadow_mode,
            "trace_id": trace_id,
        }
        if answer == self._build_empty_answer():
            verification["result"] = "empty_llm"
            return answer, sources, verification

        answer = self._strip_leading_question_echo(question=question, answer=answer)
        normalized_answer, cited_sources = self._filter_sources_to_citations(
            answer, sources
        )

        if self._looks_like_title_only_summary_answer(
            question=question, answer=normalized_answer, sources=sources
        ):
            extractive_summary = self._build_extractive_summary_answer(
                question=question,
                sources=sources,
            )
            if extractive_summary is not None:
                verification["result"] = "summary_extractive_fallback"
                verification["answer_mode"] = "extractive_summary"
                return extractive_summary[0], extractive_summary[1], verification
            verification["result"] = "summary_title_only"
            title_only_answer = (
                "I could not verify enough article content from the retrieved indexed sources "
                "to summarize it. The available evidence only identifies the article title or metadata."
            )
            return title_only_answer, [], verification

        verified = evidence_check.verify_and_normalize_answer(
            question=question,
            answer=answer,
            sources=sources,
            shadow_mode=shadow_mode,
            strip_question_echo=False,
        )
        verification.update(verified.as_dict())
        verification["trace_id"] = trace_id
        if verified.result == "no_inline_citations" and shadow_mode:
            logger.warning(
                "chat.verification.shadow_skip_no_citations %s",
                json.dumps({"trace_id": trace_id}),
            )
        if verified.result == "support_check_failed" and shadow_mode:
            logger.warning(
                "chat.verification.shadow_skip_support_check %s",
                json.dumps({"trace_id": trace_id, "question": question[:240]}),
            )
        return verified.answer, verified.sources, verification

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
        mem = chat_memory.normalize_memory(getattr(chat_session, "memory_json", None))
        if request.clear_session_memory:
            mem = chat_memory.empty_memory()
        if request.memory_items_patch:
            chat_memory.apply_memory_item_patch(mem, request.memory_items_patch)
        if request.focus_lock_document_ids:
            mem["focus_lock_document_ids"] = [
                str(x) for x in request.focus_lock_document_ids
            ][:24]
        chat_memory.prune_expired_items(mem)
        chat_session.memory_json = dict(mem)
        await self._maybe_summarize_session(
            chat_session=chat_session, messages=prior_before, mem=mem
        )
        if hasattr(self.llm_client, "last_usage"):
            self.llm_client.last_usage = None

        user_message = ChatMessage(
            session_id=chat_session.id, role="user", content=question
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
            {"role": m.role, "content": m.content} for m in prior_orm_messages
        ]

        preferred_document_ids = self._extract_preferred_document_ids(
            prior_orm_messages
        )
        preferred_chunk_refs = self._extract_preferred_chunk_refs(prior_orm_messages)
        requested_active_context_document_ids = self._parse_active_context_document_ids(
            request.active_context_document_ids
        )
        follow_up_document_ids = merge_document_ids(
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
        answer = ""
        retrieval_debug_payload: dict[str, object] = {}
        memory_applied_payload: dict[str, object] = {
            "session_summary_present": bool(mem.get("session_summary")),
            "structured_items": len(mem.get("long_term_items") or []),
            "focus_lock_count": len(mem.get("focus_lock_document_ids") or []),
        }
        rerank_stats: dict[str, object] = {}
        candidate_sources_for_metrics: list[ChatSource] | None = None
        llm_usage_summary = self._empty_llm_usage()

        try:
            plan = await plan_retrieval_query(
                question=question,
                history=history,
                llm_client=self.llm_client,
            )
            self._record_llm_usage(llm_usage_summary)
            retrieval_query = plan.retrieval_query
            is_follow_up = plan.is_follow_up
            follow_up_plan = plan.follow_up
        except Exception as exc:
            retrieval_error_type = type(exc).__name__
            logger.exception(
                "chat.retrieval_query_failed session=%s trace=%s",
                chat_session.id,
                trace_id,
            )
            answer = self._build_failure_answer(exc)
            verification_summary = {
                "result": "retrieval_query_failed",
                "error_type": retrieval_error_type,
                "shadow_mode": shadow_mode,
                "trace_id": trace_id,
            }
            observability.record_rag_stage_error(stage="retrieval_query")
        else:
            retrieval_settings_snapshot = self._retrieval_settings_snapshot(
                request=request,
                retrieval_query=retrieval_query,
                is_follow_up=is_follow_up,
                follow_up=follow_up_plan,
            )
            if is_follow_up:
                logger.debug(
                    "Follow-up detected. Rewritten query: %r Preferred docs: %s",
                    retrieval_query,
                    preferred_document_ids,
                )

            scope_plan = await plan_chat_scope(
                session=self.session,
                auth=auth,
                request=request,
                retrieval_query=retrieval_query,
                is_follow_up=is_follow_up,
                memory=mem,
                requested_active_context_document_ids=(
                    requested_active_context_document_ids
                ),
                follow_up_document_ids=follow_up_document_ids,
                active_context_document_ids=active_context_document_ids,
                shadow_mode=shadow_mode,
                trace_id=trace_id,
            )
            retrieval_document_ids = scope_plan.retrieval_document_ids
            retrieval_preferred_document_ids = (
                scope_plan.retrieval_preferred_document_ids
            )
            active_context_document_ids = scope_plan.active_context_document_ids
            filename_scoped_document_ids = scope_plan.filename_scoped_document_ids
            filename_references = scope_plan.filename_references
            filename_scope_attempted = scope_plan.filename_scope_attempted
            document_results = scope_plan.document_results
            catalog_answered = scope_plan.catalog_answered
            retrieval_debug_payload.update(scope_plan.retrieval_debug)
            if scope_plan.answer is not None:
                answer = scope_plan.answer
            if scope_plan.verification is not None:
                verification_summary = scope_plan.verification
            if document_results or catalog_answered:
                candidate_sources_for_metrics = []

            try:
                if document_results or catalog_answered:
                    retrieval = None
                elif filename_scope_attempted and not filename_scoped_document_ids:
                    retrieval = None
                    answer = self._build_no_sources_answer()
                    verification_summary = {
                        "result": "filename_reference_not_found",
                        "filename_references": filename_references,
                        "shadow_mode": shadow_mode,
                        "trace_id": trace_id,
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
                    "chat.retrieval_failed session=%s trace=%s",
                    chat_session.id,
                    trace_id,
                )
                fallback_sources = (
                    await self._build_follow_up_neighbor_sources(
                        question=question,
                        preferred_chunk_refs=preferred_chunk_refs,
                        auth=auth,
                        document_ids_scope=retrieval_document_ids,
                    )
                    if is_follow_up and preferred_chunk_refs
                    else []
                )
                if fallback_sources:
                    sources = await self._recheck_sources_authorized(
                        sources=fallback_sources,
                        auth=auth,
                        document_ids_scope=retrieval_document_ids,
                    )
                    if not sources:
                        answer = self._build_failure_answer(exc)
                        verification_summary = {
                            "result": "retrieval_failed",
                            "error_type": retrieval_error_type,
                            "shadow_mode": shadow_mode,
                            "trace_id": trace_id,
                        }
                        observability.record_rag_stage_error(stage="retrieval")
                    else:
                        fallback_sources = sources
                        memory_note = chat_memory.build_memory_prompt_block(mem)
                        style_rules = self._answer_style_rules(question)
                        fallback_overhead = build_grounded_prompt(
                            question=question,
                            sources=[],
                            history=history if history else None,
                            memory_block=memory_note or None,
                            extra_rules=style_rules,
                        )
                        fallback_pack = pack_evidence_for_prompt(
                            fallback_sources,
                            question=question,
                            history=history if history else None,
                            memory_block=memory_note or None,
                            prompt_overhead_text=fallback_overhead,
                            context_tokens=settings.RAG_PROMPT_CONTEXT_TOKENS,
                            output_reserve_tokens=settings.RAG_PROMPT_OUTPUT_RESERVE_TOKENS,
                            margin_tokens=settings.RAG_PROMPT_MARGIN_TOKENS,
                            per_source_cap_tokens=settings.RAG_PROMPT_PER_SOURCE_CAP_TOKENS,
                        )
                        fallback_sources = fallback_pack.sources
                        candidate_sources_for_metrics = fallback_sources
                        active_context_document_ids = merge_document_ids(
                            document_ids_from_sources(fallback_sources),
                            follow_up_document_ids,
                        )
                        retrieval_debug_payload = {
                            "fallback": "last_cited_neighbor_chunks",
                            "retrieval_error_type": retrieval_error_type,
                            "context_pack": fallback_pack.as_dict(),
                        }
                        try:
                            prompt = build_grounded_prompt(
                                question=question,
                                sources=fallback_sources,
                                history=history if history else None,
                                memory_block=memory_note or None,
                                extra_rules=style_rules,
                            )
                            raw_answer = (
                                await self.llm_client.generate(prompt)
                            ).strip()
                            self._record_llm_usage(llm_usage_summary)
                        except Exception as llm_exc:
                            llm_error_type = type(llm_exc).__name__
                            sources = fallback_sources[:2]
                            answer, sources, fallback_mode = (
                                self._build_source_fallback_answer(
                                    sources, mode="extractive_retrieval_llm_outage"
                                )
                            )
                            verification_summary = {
                                "result": fallback_mode,
                                "answer_mode": fallback_mode,
                                "error_type": retrieval_error_type,
                                "llm_error_type": llm_error_type,
                                "shadow_mode": shadow_mode,
                                "trace_id": trace_id,
                            }
                        else:
                            if not raw_answer:
                                sources = fallback_sources[:2]
                                answer, sources, fallback_mode = (
                                    self._build_source_fallback_answer(
                                        sources, mode="extractive_empty_llm"
                                    )
                                )
                                verification_summary = {
                                    "result": fallback_mode,
                                    "answer_mode": fallback_mode,
                                    "error_type": retrieval_error_type,
                                    "shadow_mode": shadow_mode,
                                    "trace_id": trace_id,
                                }
                            else:
                                answer, sources, verification_summary = (
                                    self._verify_and_normalize_answer(
                                        question=question,
                                        answer=raw_answer,
                                        sources=fallback_sources,
                                        shadow_mode=shadow_mode,
                                        trace_id=trace_id,
                                    )
                                )
                                verification_summary["retrieval_error_type"] = (
                                    retrieval_error_type
                                )
                                verification_summary["retrieval_fallback"] = (
                                    "last_cited_neighbor_chunks"
                                )
                else:
                    answer = self._build_failure_answer(exc)
                    verification_summary = {
                        "result": "retrieval_failed",
                        "error_type": retrieval_error_type,
                        "shadow_mode": shadow_mode,
                        "trace_id": trace_id,
                    }
                observability.record_rag_stage_error(stage="retrieval")
            else:
                if retrieval is None:
                    pass
                else:
                    previous_retrieval_debug = dict(retrieval_debug_payload)
                    retrieval_debug_payload = dict(
                        getattr(retrieval, "retrieval_debug", {}) or {}
                    )
                    retrieval_debug_payload.update(previous_retrieval_debug)
                    # Expand / auth / dedupe first — then one packing pass.
                    candidate_sources = self._prioritize_sources_for_question(
                        question=question,
                        sources=retrieval.sources,
                    )
                    if is_follow_up and preferred_chunk_refs:
                        candidate_sources = (
                            await self._augment_follow_up_sources_with_neighbors(
                                question=question,
                                sources=candidate_sources,
                                preferred_chunk_refs=preferred_chunk_refs,
                                auth=auth,
                                document_ids_scope=retrieval_document_ids,
                            )
                        )
                    candidate_sources = (
                        await self._augment_question_sources_from_same_documents(
                            question=question,
                            sources=candidate_sources,
                            max_sources=max(20, request.top_k * 3),
                            auth=auth,
                            document_ids_scope=retrieval_document_ids,
                        )
                    )
                    candidate_sources = (
                        await self._augment_summary_sources_from_same_documents(
                            question=question,
                            sources=candidate_sources,
                            max_sources=max(12, request.top_k * 2),
                            auth=auth,
                            document_ids_scope=retrieval_document_ids,
                        )
                    )
                    candidate_sources = await self._recheck_sources_authorized(
                        sources=candidate_sources,
                        auth=auth,
                        document_ids_scope=retrieval_document_ids,
                    )
                    candidate_sources = self._dedupe_employment_sources(
                        candidate_sources
                    )
                    candidate_sources, constraint_debug = (
                        self._filter_sources_for_question_constraints(
                            question=question,
                            sources=candidate_sources,
                        )
                    )
                    if constraint_debug.get("time_filter_applied"):
                        retrieval_debug_payload["question_constraints"] = (
                            constraint_debug
                        )

                    memory_note = chat_memory.build_memory_prompt_block(mem)
                    style_rules = self._answer_style_rules(question)
                    prompt_overhead = build_grounded_prompt(
                        question=question,
                        sources=[],
                        history=history if history else None,
                        memory_block=memory_note or None,
                        extra_rules=style_rules,
                    )
                    packed = pack_evidence_for_prompt(
                        candidate_sources,
                        question=question,
                        history=history if history else None,
                        memory_block=memory_note or None,
                        prompt_overhead_text=prompt_overhead,
                        context_tokens=settings.RAG_PROMPT_CONTEXT_TOKENS,
                        output_reserve_tokens=settings.RAG_PROMPT_OUTPUT_RESERVE_TOKENS,
                        margin_tokens=settings.RAG_PROMPT_MARGIN_TOKENS,
                        per_source_cap_tokens=settings.RAG_PROMPT_PER_SOURCE_CAP_TOKENS,
                    )
                    candidate_sources = packed.sources
                    rerank_stats.update(packed.as_dict())
                    retrieval_debug_payload["context_pack"] = packed.as_dict()
                    candidate_sources_for_metrics = candidate_sources
                    grounded_document_ids = getattr(
                        retrieval, "grounded_document_ids", []
                    )
                    active_context_document_ids = merge_document_ids(
                        list(grounded_document_ids),
                        document_ids_from_sources(candidate_sources),
                        follow_up_document_ids,
                    )

                    if not candidate_sources:
                        answer = self._build_no_sources_answer()
                        sources = []
                        verification_summary = {
                            "result": "no_sources",
                            "shadow_mode": shadow_mode,
                            "trace_id": trace_id,
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
                                prompt = build_grounded_prompt(
                                    question=question,
                                    sources=candidate_sources,
                                    history=history if history else None,
                                    memory_block=memory_note or None,
                                    extra_rules=style_rules,
                                )
                                raw_answer = (
                                    await self.llm_client.generate(prompt)
                                ).strip()
                                self._record_llm_usage(llm_usage_summary)
                            except Exception as exc:
                                llm_error_type = type(exc).__name__
                                logger.exception(
                                    "chat.llm_failed session=%s trace=%s",
                                    chat_session.id,
                                    trace_id,
                                )
                                mode = (
                                    "extractive_llm_timeout"
                                    if isinstance(
                                        exc, (httpx.TimeoutException, LLMTimeoutError)
                                    )
                                    else "extractive_llm_outage"
                                )
                                answer, sources, fallback_mode = (
                                    self._build_source_fallback_answer(
                                        candidate_sources, mode=mode
                                    )
                                )
                                verification_summary = {
                                    "result": fallback_mode,
                                    "answer_mode": fallback_mode,
                                    "error_type": (
                                        getattr(exc, "error_type", None)
                                        or type(exc).__name__
                                    ),
                                    "shadow_mode": shadow_mode,
                                    "trace_id": trace_id,
                                }
                                observability.record_rag_stage_error(stage="llm")
                            else:
                                if not raw_answer:
                                    answer, sources, fallback_mode = (
                                        self._build_source_fallback_answer(
                                            candidate_sources,
                                            mode="extractive_empty_llm",
                                        )
                                    )
                                    verification_summary = {
                                        "result": fallback_mode,
                                        "answer_mode": fallback_mode,
                                        "shadow_mode": shadow_mode,
                                        "trace_id": trace_id,
                                    }
                                else:
                                    answer, sources, verification_summary = (
                                        self._verify_and_normalize_answer(
                                            question=question,
                                            answer=raw_answer,
                                            sources=candidate_sources,
                                            shadow_mode=shadow_mode,
                                            trace_id=trace_id,
                                        )
                                    )

        return await finalize_chat_completion(
            session=self.session,
            message_repo=self.message_repo,
            chat_session=chat_session,
            user_message=user_message,
            request=request,
            completion=ChatCompletion(
                answer=answer,
                sources=sources,
                document_results=document_results,
                active_context_document_ids=active_context_document_ids,
                follow_up_document_ids=follow_up_document_ids,
                retrieval_query=retrieval_query,
                trace_id=trace_id,
                llm_provider=llm_provider,
                llm_model_id=llm_model_id,
                prompt_version=prompt_version,
                retrieval_settings=retrieval_settings_snapshot,
                verification=verification_summary,
                retrieval_debug=retrieval_debug_payload,
                memory_applied=memory_applied_payload,
                llm_usage=llm_usage_summary,
                memory=mem,
                shadow_mode=shadow_mode,
                rerank_stats=rerank_stats,
                candidate_source_count=(
                    len(candidate_sources_for_metrics)
                    if candidate_sources_for_metrics is not None
                    else None
                ),
                retrieval_error_type=retrieval_error_type,
                llm_error_type=llm_error_type,
            ),
        )
