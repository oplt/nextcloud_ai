from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.llm_client import LLMClientFactory, LLMClientProtocol
from backend.ai.prompt_builder import build_grounded_prompt
from backend.services.query_writer import build_retrieval_query
from backend.core.exceptions import AuthorizationError, NotFoundError
from backend.core.security import AuthContext
from backend.db.models import ChatMessage, ChatSession, User
from backend.db.repo.chat import ChatMessageRepository, ChatSessionRepository
from backend.schemas.chat_schema import ChatAskRequest, ChatAskResponse, ChatSource
from backend.services.audit_service import AuditService
from backend.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)
_CITATION_RE = re.compile(r"\[(\d+)\]")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_YEAR_RANGE_RE = re.compile(
    r"\b(?:[A-Za-z]{3,9}\s+)?(?P<start>(?:19|20)\d{2})\b"
    r"\s*(?:-|–|—|to|through|until)\s*"
    r"(?:(?:[A-Za-z]{3,9}\s+)?(?P<end>(?:19|20)\d{2})|(?P<open>present|current|now))",
    flags=re.IGNORECASE,
)
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
        return list(dict.fromkeys(_YEAR_RE.findall(question)))

    @staticmethod
    def _extract_year_ranges(text: str) -> list[tuple[int, int]]:
        ranges: list[tuple[int, int]] = []
        current_year = datetime.now(timezone.utc).year
        for match in _YEAR_RANGE_RE.finditer(text):
            start_year = int(match.group('start'))
            end_year = int(match.group('end')) if match.group('end') else current_year
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

    @classmethod
    def _source_year_match_status(cls, *, source: ChatSource, years: list[str]) -> int:
        source_text = (source.content or source.snippet or '').strip()
        if not years or not source_text:
            return 0
        if all(cls._text_supports_year(source_text, year) for year in years):
            return 1
        if _YEAR_RE.search(source_text):
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
                has_employment_markers = bool(_EMPLOYMENT_HINT_RE.search(source_text))
                has_education_markers = bool(_EDUCATION_HINT_RE.search(source_text))
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
        lowered = question.lower()
        employment_terms = (' work ', ' worked ', ' employer ', ' employed ', ' employment ', ' company ', ' job ', ' role ')
        return any(term in f' {lowered} ' for term in employment_terms)

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
                if _YEAR_RE.fullmatch(candidate) or not any(char.isalpha() for char in candidate):
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

    def _normalize_answer_and_sources(
        self,
        *,
        question: str,
        answer: str,
        sources: list[ChatSource],
    ) -> tuple[str, list[ChatSource]]:
        normalized_answer, cited_sources = self._filter_sources_to_citations(answer, sources)
        if self._is_insufficient_answer(normalized_answer):
            return normalized_answer, []
        if not cited_sources:
            return self._build_unverified_answer(question), []
        if not self._answer_is_supported(question=question, answer=normalized_answer, cited_sources=cited_sources):
            return self._build_unverified_answer(question), []
        return normalized_answer, cited_sources

    async def ask(
        self, *, user: User, auth: AuthContext, request: ChatAskRequest
    ) -> ChatAskResponse:
        question = request.question.strip() or request.question
        chat_session = await self._get_or_create_session(user=user, request=request)

        user_message = ChatMessage(
            session_id=chat_session.id, role='user', content=question
        )
        self._touch_session(chat_session)
        await self.message_repo.add(user_message, flush=True)
        await self.session.commit()
        await self.session.refresh(user_message)
        await self.session.refresh(chat_session)

        prior_orm_messages: list[ChatMessage] = await self.message_repo.list_by_session(
            chat_session.id, limit=_HISTORY_WINDOW
        )
        prior_orm_messages = [m for m in prior_orm_messages if m.id != user_message.id]
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

        retrieval_query, is_follow_up = await build_retrieval_query(
            question=question,
            history=history,
            llm_client=self.llm_client,
        )
        if is_follow_up:
            logger.debug(
                'Follow-up detected. Rewritten query: %r Preferred docs: %s',
                retrieval_query,
                preferred_document_ids,
            )

        sources: list[ChatSource] = []
        active_context_document_ids = follow_up_document_ids
        try:
            explicit_document_ids = request.document_ids or None
            retrieval_document_ids = explicit_document_ids
            retrieval_preferred_document_ids = None
            if (
                requested_active_context_document_ids
                and is_follow_up
                and explicit_document_ids is None
            ):
                retrieval_document_ids = requested_active_context_document_ids
            elif follow_up_document_ids and is_follow_up and explicit_document_ids is None:
                retrieval_preferred_document_ids = follow_up_document_ids

            retrieval = await self.retrieval_service.retrieve(
                question=retrieval_query,
                auth=auth,
                top_k=request.top_k,
                document_ids=retrieval_document_ids,
                preferred_document_ids=retrieval_preferred_document_ids,
            )
            candidate_sources = self._prioritize_sources_for_question(
                question=question,
                sources=retrieval.sources,
            )
            grounded_document_ids = getattr(retrieval, 'grounded_document_ids', [])
            active_context_document_ids = self._merge_document_ids(
                list(grounded_document_ids),
                self._extract_document_ids_from_sources(candidate_sources),
                follow_up_document_ids,
            )

            if candidate_sources:
                prompt = build_grounded_prompt(
                    question=question,
                    sources=candidate_sources,
                    history=history if history else None,
                )
                answer = (await self.llm_client.generate(prompt)).strip()
                if not answer:
                    answer = self._build_empty_answer()
            else:
                answer = self._build_no_sources_answer()

            answer, sources = self._normalize_answer_and_sources(
                question=question,
                answer=answer,
                sources=candidate_sources,
            )
        except Exception as exc:
            logger.exception('Chat answer generation failed for session %s', chat_session.id)
            answer = self._build_failure_answer(exc)
            sources = []

        cited_document_ids = self._extract_document_ids_from_sources(sources)
        if cited_document_ids:
            active_context_document_ids = self._merge_document_ids(cited_document_ids, follow_up_document_ids)

        assistant_message = ChatMessage(
            session_id=chat_session.id,
            role='assistant',
            content=answer,
            citations_json=([source.model_dump(mode='json') for source in sources] or None),
            model_name=self.llm_client.__class__.__name__,
        )
        self._touch_session(chat_session)
        await self.message_repo.add(assistant_message, flush=True)
        await self.session.commit()
        await self.session.refresh(assistant_message)
        await self.session.refresh(chat_session)

        return ChatAskResponse(
            session_id=chat_session.id,
            answer=answer,
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
        )
