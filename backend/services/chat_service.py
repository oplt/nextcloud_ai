from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai import rag_temporal
from backend.ai.follow_up_classifier import FollowUpClassification
from backend.ai import session_memory as chat_memory
from backend.ai.llm_client import LLMClientFactory, LLMClientProtocol
from backend.ai.prompt_builder import GROUNDED_PROMPT_VERSION, build_grounded_prompt
from backend.ai.rag_postprocess import rerank_and_truncate_sources
from backend.services.query_writer import plan_retrieval_query
from backend.core import observability
from backend.core.config import settings
from backend.core.exceptions import AuthorizationError, NotFoundError
from backend.core.security import AuthContext
from backend.db.models import ChatMessage, ChatSession, User
from backend.db.repo.chat import ChatMessageRepository, ChatSessionRepository
from backend.schemas.chat_schema import (
    ChatAskRequest,
    ChatAskResponse,
    ChatMemoryPatchRequest,
    ChatSource,
)
from backend.services.audit_service import AuditService
from backend.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)
_CITATION_RE = re.compile(r"\[(\d+)\]")
_EMPLOYMENT_ORG_RE = re.compile(
    r"\b(?:work(?:ed)?|employed|employment|job|role|position)\b.{0,60}?\b(?:at|in|for)\s+([A-Za-z0-9&./'\-]+(?:\s+[A-Za-z0-9&./'\-]+){0,5})",
    flags=re.IGNORECASE,
)
_PREPOSITION_ORG_RE = re.compile(
    r"\b(?:at|in|for)\s+([A-Za-z0-9&./'\-]+(?:\s+[A-Za-z0-9&./'\-]+){0,5})",
    flags=re.IGNORECASE,
)
_GENERIC_ORG_TERMS = {
    'the', 'a', 'an', 'company', 'organization', 'role', 'job', 'position', 'year',
    'there', 'that', 'this', 'his', 'her', 'their', 'where', 'what', 'when', 'who',
}
_INSUFFICIENT_MARKERS = (
    'could not verify',
    'could not find',
    'not enough',
    'insufficient',
    'do not have enough',
    'no indexed source',
    'no source',
)
_NEGATION_MARKERS = (
    ' did not ',
    " didn't ",
    ' never ',
    ' no evidence ',
    ' not work ',
    ' was not ',
    ' were not ',
)

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
    def _is_insufficient_answer(answer: str) -> bool:
        lowered = f" {answer.lower()} "
        return any(marker in lowered for marker in _INSUFFICIENT_MARKERS)

    @staticmethod
    def _question_years(question: str) -> list[str]:
        return rag_temporal.extract_question_years(question)

    @staticmethod
    def _text_supports_year(text: str, year: str) -> bool:
        return rag_temporal.text_supports_year(
            text, year, open_end_policy="current_year"
        )

    @classmethod
    def _source_year_match_status(cls, *, source: ChatSource, years: list[str]) -> int:
        source_text = (source.content or source.snippet or '').strip()
        if not years or not source_text:
            return 0
        if all(ChatService._text_supports_year(source_text, year) for year in years):
            return 1
        if rag_temporal.year_literal_present(source_text):
            return -1
        return 0

    @classmethod
    def _prioritize_sources_for_question(
        cls,
        *,
        question: str,
        sources: list[ChatSource],
    ) -> list[ChatSource]:
        years = cls._question_years(question)
        employment_question = cls._looks_like_employment_question(question)
        if not years and not employment_question:
            return sources

        ranked_sources: list[tuple[int, int, float, int, ChatSource]] = []
        for index, source in enumerate(sources):
            source_text = (source.content or source.snippet or '').strip()
            employment_status = 0
            if employment_question and source_text:
                has_employment_markers = rag_temporal.employment_markers_present(source_text)
                has_education_markers = rag_temporal.education_markers_present(source_text)
                if has_employment_markers:
                    employment_status = 1
                elif has_education_markers:
                    employment_status = -1
            ranked_sources.append(
                (
                    cls._source_year_match_status(source=source, years=years) if years else 0,
                    employment_status,
                    source.score,
                    index,
                    source,
                )
            )

        if years and any(year_status > 0 for year_status, _, _, _, _ in ranked_sources):
            ranked_sources = [
                item for item in ranked_sources if item[0] > 0
            ]

        if employment_question and any(employment_status > 0 for _, employment_status, _, _, _ in ranked_sources):
            ranked_sources = [
                item for item in ranked_sources if item[1] >= 0
            ]

        ranked_sources.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
        return [source for _, _, _, _, source in ranked_sources]

    @staticmethod
    def _looks_like_employment_question(question: str) -> bool:
        return rag_temporal.looks_like_employment_question(question)

    @staticmethod
    def _looks_like_claim_challenge(question: str) -> bool:
        lowered = f" {question.lower()} "
        challenge_terms = (' not ', ' never ', ' wrong ', ' incorrect ', ' are you sure ', ' he never ', ' she never ')
        return any(term in lowered for term in challenge_terms)

    @staticmethod
    def _normalize_organization_candidate(candidate: str) -> str:
        normalized = ' '.join(candidate.strip().split()).lower().strip(' .,:;')
        for article in ('the ', 'a ', 'an '):
            if normalized.startswith(article):
                normalized = normalized[len(article):].strip(' .,:;')
        for separator in (' from ', ' as ', ' during ', ' between ', ' since ', ' until ', ' | '):
            if separator in normalized:
                normalized = normalized.split(separator, 1)[0].strip(' .,:;')
        if ' in ' in normalized:
            prefix = normalized.split(' in ', 1)[0].strip(' .,:;')
            if sum(1 for token in prefix.split() if any(char.isalpha() for char in token)) >= 2:
                normalized = prefix
        return normalized

    @classmethod
    def _extract_target_organizations(cls, text: str) -> list[str]:
        matches: list[str] = []
        for regex in (_EMPLOYMENT_ORG_RE, _PREPOSITION_ORG_RE):
            for match in regex.findall(text):
                candidate = cls._normalize_organization_candidate(str(match))
                if not candidate:
                    continue
                if candidate in _GENERIC_ORG_TERMS:
                    continue
                if rag_temporal.is_year_token(candidate) or not any(char.isalpha() for char in candidate):
                    continue
                if candidate not in matches:
                    matches.append(candidate)
        return matches

    @staticmethod
    def _source_texts(sources: list[ChatSource]) -> list[str]:
        texts: list[str] = []
        for source in sources:
            source_text = (source.content or source.snippet or '').strip()
            if source_text:
                texts.append(f" {source_text.lower()} ")
        return texts

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

        answer_lowered = f" {answer.lower()} "
        years = self._question_years(question)
        target_organizations = self._extract_target_organizations(question)
        answer_organizations = self._extract_target_organizations(answer)
        if answer_organizations:
            target_organizations = list(dict.fromkeys([*target_organizations, *answer_organizations]))

        if any(marker in answer_lowered for marker in _NEGATION_MARKERS):
            for org in target_organizations or ['']:
                if not org:
                    continue
                if not any(org in text and any(marker in text for marker in _NEGATION_MARKERS) for text in source_texts):
                    return False
            return True

        if years and target_organizations:
            for organization in target_organizations:
                if not any(
                    organization in text and all(self._text_supports_year(text, year) for year in years)
                    for text in source_texts
                ):
                    return False
            return True

        if years and not any(
            all(self._text_supports_year(text, year) for year in years)
            for text in source_texts
        ):
            return False

        if target_organizations and not all(
            any(organization in text for text in source_texts)
            for organization in target_organizations
        ):
            return False

        if self._looks_like_employment_question(question) and not target_organizations and years:
            return any(
                all(self._text_supports_year(text, year) for year in years)
                for text in source_texts
            )

        return True

    def _build_unverified_answer(self, question: str) -> str:
        years = self._question_years(question)
        if self._looks_like_employment_question(question):
            year_suffix = f" for {' and '.join(years)}" if years else ''
            return f'I could not verify the employer{year_suffix} from the indexed sources.'
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

        normalized_answer, cited_sources = self._filter_sources_to_citations(answer, sources)
        if self._is_insufficient_answer(normalized_answer):
            verification['result'] = 'insufficient_answer'
            return normalized_answer, [], verification

        if not cited_sources:
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
        active_context_document_ids = follow_up_document_ids
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

            explicit_document_ids = request.document_ids or None
            retrieval_document_ids = explicit_document_ids
            retrieval_preferred_document_ids = None
            lock_ids = self._parse_active_context_document_ids(
                [str(x) for x in (mem.get('focus_lock_document_ids') or [])]
            )
            if lock_ids and explicit_document_ids is None:
                retrieval_document_ids = lock_ids
            if (
                requested_active_context_document_ids
                and is_follow_up
                and explicit_document_ids is None
                and not lock_ids
            ):
                retrieval_document_ids = requested_active_context_document_ids
            elif follow_up_document_ids and is_follow_up and explicit_document_ids is None and not lock_ids:
                retrieval_preferred_document_ids = follow_up_document_ids

            try:
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
                answer = self._build_failure_answer(exc)
                verification_summary = {
                    'result': 'retrieval_failed',
                    'error_type': retrieval_error_type,
                    'shadow_mode': shadow_mode,
                    'trace_id': trace_id,
                }
                observability.record_rag_stage_error(stage='retrieval')
            else:
                retrieval_debug_payload = dict(
                    getattr(retrieval, 'retrieval_debug', {}) or {}
                )
                candidate_sources = rerank_and_truncate_sources(
                    question,
                    self._prioritize_sources_for_question(
                        question=question,
                        sources=retrieval.sources,
                    ),
                    stats_out=rerank_stats,
                )
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
                    try:
                        memory_note = chat_memory.build_memory_prompt_block(mem)
                        prompt = build_grounded_prompt(
                            question=question,
                            sources=candidate_sources,
                            history=history if history else None,
                            memory_block=memory_note or None,
                        )
                        raw_answer = (await self.llm_client.generate(prompt)).strip()
                    except Exception as exc:
                        llm_error_type = type(exc).__name__
                        logger.exception(
                            'chat.llm_failed session=%s trace=%s',
                            chat_session.id,
                            trace_id,
                        )
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
