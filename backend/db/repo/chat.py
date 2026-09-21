from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import ChatMessage, ChatSession
from .base import BaseRepository


class ChatSessionRepository(BaseRepository[ChatSession]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ChatSession)

    async def list_by_user(
        self, user_id: UUID | str, *, offset: int = 0, limit: int = 50
    ) -> list[ChatSession]:
        """List sessions without loading message bodies.

        Subject preview comes from the latest message via a scalar subquery.
        Full message history requires :meth:`get_with_messages`.
        """
        latest_content = (
            select(ChatMessage.content)
            .where(ChatMessage.session_id == ChatSession.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        message_count = (
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.session_id == ChatSession.id)
            .correlate(ChatSession)
            .scalar_subquery()
        )
        result = await self.session.execute(
            select(ChatSession, latest_content, message_count)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        sessions: list[ChatSession] = []
        for session, preview, count in result.all():
            session._subject_preview = preview or session.title  # type: ignore[attr-defined]
            session._message_count = int(count or 0)  # type: ignore[attr-defined]
            sessions.append(session)
        return sessions

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

    async def list_by_session(
        self,
        session_id: UUID | str,
        limit: int | None = None,
    ) -> list[ChatMessage]:
        if limit is None:
            result = await self.session.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc())
            )
            return list(result.scalars().all())

        result = await self.session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        messages = list(result.scalars().all())
        messages.reverse()
        return messages
