from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.models import ChatMessage, ChatSession
from backend.db.repo.base import BaseRepository


class ChatSessionRepository(BaseRepository[ChatSession]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ChatSession)

    async def list_by_user(
        self, user_id: UUID | str, *, offset: int = 0, limit: int = 50
    ) -> list[ChatSession]:
        result = await self.session.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_with_messages(self, session_id: UUID | str) -> ChatSession | None:
        result = await self.session.execute(
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .where(ChatSession.id == session_id)
        )
        return result.scalar_one_or_none()


class ChatMessageRepository(BaseRepository[ChatMessage]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ChatMessage)

    async def list_by_session(self, session_id: UUID | str) -> list[ChatMessage]:
        result = await self.session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        return list(result.scalars().all())
