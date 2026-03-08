from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.llm_client import LLMClientFactory, LLMClientProtocol
from backend.ai.prompt_builder import build_grounded_prompt
from backend.core.exceptions import AuthorizationError, NotFoundError
from backend.core.security import AuthContext
from backend.db.models import ChatMessage, ChatSession, User
from backend.db.repo.chat import ChatMessageRepository, ChatSessionRepository
from backend.schemas.chat_schema import ChatAskRequest, ChatAskResponse
from backend.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)


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

    async def _get_or_create_session(
        self, *, user: User, request: ChatAskRequest
    ) -> ChatSession:
        if request.session_id:
            existing = await self.session_repo.get(request.session_id)
            if existing is None:
                raise NotFoundError("Chat session not found")
            if existing.user_id != user.id:
                raise AuthorizationError("Chat session does not belong to this user")
            return existing

        chat_session = ChatSession(
            user_id=user.id, title=request.question.strip()[:80] or "New chat"
        )
        await self.session_repo.add(chat_session, flush=True)
        return chat_session

    @staticmethod
    def _touch_session(chat_session: ChatSession) -> None:
        chat_session.updated_at = datetime.now(timezone.utc)

    @staticmethod
    def _build_no_sources_answer() -> str:
        return (
            "I could not find indexed source material for that question. "
            "The relevant file may not be synced yet, may not have been chunked and embedded, "
            "or you may not have access to it."
        )

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

    async def ask(
        self, *, user: User, auth: AuthContext, request: ChatAskRequest
    ) -> ChatAskResponse:
        question = request.question.strip() or request.question
        chat_session = await self._get_or_create_session(user=user, request=request)

        user_message = ChatMessage(
            session_id=chat_session.id, role="user", content=question
        )
        self._touch_session(chat_session)
        await self.message_repo.add(user_message, flush=True)
        await self.session.commit()
        await self.session.refresh(user_message)
        await self.session.refresh(chat_session)

        sources = []
        try:
            retrieval = await self.retrieval_service.retrieve(
                question=question,
                auth=auth,
                top_k=request.top_k,
                document_ids=request.document_ids,
            )
            sources = retrieval.sources
            if sources:
                prompt = build_grounded_prompt(question=question, sources=sources)
                answer = (await self.llm_client.generate(prompt)).strip()
                if not answer:
                    answer = self._build_empty_answer()
            else:
                answer = self._build_no_sources_answer()
        except Exception as exc:
            logger.exception(
                "Chat answer generation failed for session %s", chat_session.id
            )
            answer = self._build_failure_answer(exc)

        assistant_message = ChatMessage(
            session_id=chat_session.id,
            role="assistant",
            content=answer,
            citations_json=(
                [source.model_dump(mode="json") for source in sources] or None
            ),
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
        )
