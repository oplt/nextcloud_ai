from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from backend.core.security import AuthContext
from backend.db.models import ChatMessage, ChatSession, User
from backend.schemas.chat_schema import ChatAskRequest, ChatSource
from backend.services.chat_service import ChatService


class FakeAsyncSession:
    def __init__(self) -> None:
        self.commits = 0
        self.refreshed: list[object] = []

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, instance: object) -> None:
        self.refreshed.append(instance)


class FakeChatSessionRepository:
    def __init__(self, existing: ChatSession | None = None) -> None:
        self.existing = existing
        self.items: list[ChatSession] = []

    async def add(self, instance: ChatSession, *, flush: bool = False) -> ChatSession:
        if instance.id is None:
            instance.id = uuid4()
        self.items.append(instance)
        self.existing = instance
        return instance

    async def get(self, session_id) -> ChatSession | None:
        if self.existing is not None and self.existing.id == session_id:
            return self.existing
        return None


class FakeChatMessageRepository:
    def __init__(self) -> None:
        self.items: list[ChatMessage] = []

    async def add(self, instance: ChatMessage, *, flush: bool = False) -> ChatMessage:
        if instance.id is None:
            instance.id = uuid4()
        self.items.append(instance)
        return instance


class FailingRetrievalService:
    async def retrieve(self, **kwargs):
        request = httpx.Request("POST", "http://localhost:11434/api/embeddings")
        raise httpx.ConnectError("connection refused", request=request)


class EmptyRetrievalService:
    async def retrieve(self, **kwargs):
        return SimpleNamespace(sources=[], query_embedding=[])


class StaticRetrievalService:
    def __init__(self, sources: list[ChatSource]) -> None:
        self.sources = sources

    async def retrieve(self, **kwargs):
        return SimpleNamespace(sources=self.sources, query_embedding=[0.1, 0.2])


class GuardLLMClient:
    def __init__(self) -> None:
        self.called = False

    async def generate(self, prompt: str) -> str:
        self.called = True
        raise AssertionError("generate should not be called")


class EmptyLLMClient:
    async def generate(self, prompt: str) -> str:
        return "   "


def _build_service(
    *,
    retrieval_service,
    llm_client,
    existing_session: ChatSession | None = None,
) -> tuple[ChatService, FakeAsyncSession, FakeChatSessionRepository, FakeChatMessageRepository]:
    session = FakeAsyncSession()
    service = ChatService(
        session=session,
        retrieval_service=retrieval_service,
        llm_client=llm_client,
    )
    session_repo = FakeChatSessionRepository(existing=existing_session)
    message_repo = FakeChatMessageRepository()
    service.session_repo = session_repo
    service.message_repo = message_repo
    return service, session, session_repo, message_repo


def _build_user() -> User:
    return User(id=uuid4(), auth_provider="local", username="alice")


def _build_auth(user: User) -> AuthContext:
    return AuthContext(user_id=str(user.id), auth_provider="local", username=user.username)


@pytest.mark.asyncio
async def test_chat_service_persists_user_question_and_failure_answer_when_retrieval_fails() -> None:
    user = _build_user()
    service, session, session_repo, message_repo = _build_service(
        retrieval_service=FailingRetrievalService(),
        llm_client=GuardLLMClient(),
    )

    response = await service.ask(
        user=user,
        auth=_build_auth(user),
        request=ChatAskRequest(question="Why was there no answer?"),
    )

    assert len(session_repo.items) == 1
    assert len(message_repo.items) == 2
    assert message_repo.items[0].role == "user"
    assert message_repo.items[0].content == "Why was there no answer?"
    assert message_repo.items[1].role == "assistant"
    assert "service was unreachable" in message_repo.items[1].content
    assert "saved in the chat history" in message_repo.items[1].content
    assert response.answer == message_repo.items[1].content
    assert response.sources == []
    assert session.commits == 2


@pytest.mark.asyncio
async def test_chat_service_returns_immediate_fallback_when_no_sources_found() -> None:
    user = _build_user()
    llm_client = GuardLLMClient()
    service, session, session_repo, message_repo = _build_service(
        retrieval_service=EmptyRetrievalService(),
        llm_client=llm_client,
    )

    response = await service.ask(
        user=user,
        auth=_build_auth(user),
        request=ChatAskRequest(question="Tell me about a file that was never indexed"),
    )

    assert len(session_repo.items) == 1
    assert len(message_repo.items) == 2
    assert llm_client.called is False
    assert "could not find indexed source material" in response.answer
    assert response.sources == []
    assert session.commits == 2


@pytest.mark.asyncio
async def test_chat_service_replaces_empty_llm_output_and_refreshes_existing_session() -> None:
    user = _build_user()
    old_updated_at = datetime.now(timezone.utc) - timedelta(days=1)
    existing_session = ChatSession(
        id=uuid4(),
        user_id=user.id,
        title="Existing chat",
        updated_at=old_updated_at,
    )
    sources = [
        ChatSource(
            chunk_id=uuid4(),
            document_id=uuid4(),
            file_name="policy.md",
            file_path="/docs/policy.md",
            page_number=None,
            section_title="Policy",
            snippet="The policy says the answer is documented here.",
            distance=0.1,
            score=0.92,
        )
    ]
    service, session, session_repo, message_repo = _build_service(
        retrieval_service=StaticRetrievalService(sources),
        llm_client=EmptyLLMClient(),
        existing_session=existing_session,
    )

    response = await service.ask(
        user=user,
        auth=_build_auth(user),
        request=ChatAskRequest(
            question="What does the policy say?",
            session_id=existing_session.id,
        ),
    )

    assert session_repo.existing is existing_session
    assert len(message_repo.items) == 2
    assert response.sources == sources
    assert "language model returned an empty response" in response.answer
    assert existing_session.updated_at is not None
    assert existing_session.updated_at > old_updated_at
    assert session.commits == 2
