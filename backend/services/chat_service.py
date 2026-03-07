from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.llm_client import LLMClientFactory, LLMClientProtocol
from backend.ai.prompt_builder import build_grounded_prompt
from backend.core.exceptions import AuthorizationError, NotFoundError
from backend.core.security import AuthContext
from backend.db.models import ChatMessage, ChatSession, User
from backend.db.repo.chat import ChatMessageRepository, ChatSessionRepository
from backend.schemas.chat_schema import ChatAskRequest, ChatAskResponse
from backend.services.retrieval_service import RetrievalService


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

    async def ask(
        self, *, user: User, auth: AuthContext, request: ChatAskRequest
    ) -> ChatAskResponse:
        chat_session = await self._get_or_create_session(user=user, request=request)
        retrieval = await self.retrieval_service.retrieve(
            question=request.question,
            auth=auth,
            top_k=request.top_k,
            document_ids=request.document_ids,
        )
        prompt = build_grounded_prompt(
            question=request.question, sources=retrieval.sources
        )
        answer = await self.llm_client.generate(prompt)

        user_message = ChatMessage(
            session_id=chat_session.id, role="user", content=request.question
        )
        assistant_message = ChatMessage(
            session_id=chat_session.id,
            role="assistant",
            content=answer,
            citations_json=[
                source.model_dump(mode="json") for source in retrieval.sources
            ],
            model_name=self.llm_client.__class__.__name__,
        )
        await self.message_repo.add(user_message)
        await self.message_repo.add(assistant_message, flush=True)
        await self.session.commit()
        await asyncio.gather(
            self.session.refresh(user_message),
            self.session.refresh(assistant_message),
            self.session.refresh(chat_session),
        )
        return ChatAskResponse(
            session_id=chat_session.id,
            answer=answer,
            sources=retrieval.sources,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
        )
