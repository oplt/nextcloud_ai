from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.llm_client import LLMClientProtocol, SimpleGroundedLLMClient
from backend.ai.prompt_builder import build_grounded_prompt
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
        self.llm_client = llm_client or SimpleGroundedLLMClient()

        self.session_repo = ChatSessionRepository(session)
        self.message_repo = ChatMessageRepository(session)

    async def _get_or_create_session(
            self,
            *,
            user: User,
            request: ChatAskRequest,
    ) -> ChatSession:
        if request.session_id:
            existing = await self.session_repo.get(request.session_id)
            # BUG FIX: silently creating a new session when session_id is
            # provided but not found or belongs to another user is wrong —
            # raise instead so the caller knows something went wrong.
            if existing is None:
                raise ValueError(f"Chat session {request.session_id!r} not found")
            if existing.user_id != user.id:
                raise PermissionError(
                    f"Chat session {request.session_id!r} does not belong to this user"
                )
            return existing

        title = request.question.strip()[:80] or "New chat"
        chat_session = ChatSession(
            user_id=user.id,
            title=title,
        )
        # No flush needed here — we flush once before we need the id below.
        await self.session_repo.add(chat_session, flush=True)
        return chat_session

    async def ask(
            self,
            *,
            user: User,
            request: ChatAskRequest,
    ) -> ChatAskResponse:
        chat_session = await self._get_or_create_session(user=user, request=request)

        retrieval = await self.retrieval_service.retrieve(
            question=request.question,
            top_k=request.top_k,
            document_ids=request.document_ids,
        )

        prompt = build_grounded_prompt(
            question=request.question,
            sources=retrieval.sources,
        )
        answer = await self.llm_client.generate(prompt)

        user_message = ChatMessage(
            session_id=chat_session.id,
            role="user",
            content=request.question,
            retrieved_chunks_json=None,
            model_name=None,
        )
        assistant_message = ChatMessage(
            session_id=chat_session.id,
            role="assistant",
            content=answer,
            retrieved_chunks_json=[source.model_dump(mode="json") for source in retrieval.sources],
            model_name=self.llm_client.__class__.__name__,
        )

        # PERF FIX: avoid a redundant flush on the first add — batch both
        # messages and flush only once so we get their ids assigned in a
        # single round-trip.
        await self.message_repo.add(user_message)
        await self.message_repo.add(assistant_message, flush=True)

        await self.session.commit()

        # PERF FIX: refresh all three objects concurrently instead of
        # awaiting them one after another.
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