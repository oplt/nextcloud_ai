from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

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
        self.deleted_ids: list[UUID] = []

    async def add(self, instance: ChatSession, *, flush: bool = False) -> ChatSession:
        if instance.id is None:
            instance.id = uuid4()
        self.items.append(instance)
        self.existing = instance
        return instance

    async def get(self, session_id) -> ChatSession | None:
        if self.existing is not None and str(self.existing.id) == str(session_id):
            return self.existing
        return None

    async def delete(self, instance: ChatSession, *, flush: bool = False) -> None:
        self.deleted_ids.append(instance.id)
        if self.existing is not None and self.existing.id == instance.id:
            self.existing = None
        self.items = [item for item in self.items if item.id != instance.id]


class FakeChatMessageRepository:
    def __init__(self, items: list[ChatMessage] | None = None) -> None:
        self.items: list[ChatMessage] = list(items or [])

    async def add(self, instance: ChatMessage, *, flush: bool = False) -> ChatMessage:
        if instance.id is None:
            instance.id = uuid4()
        self.items.append(instance)
        return instance

    async def list_by_session(
        self,
        session_id,
        limit: int | None = None,
    ) -> list[ChatMessage]:
        session_items = [item for item in self.items if item.session_id == session_id]
        if limit is None:
            return session_items
        return session_items[-limit:]


class FailingRetrievalService:
    async def retrieve(self, **kwargs):
        request = httpx.Request("POST", "http://localhost:11434/api/embeddings")
        raise httpx.ConnectError("connection refused", request=request)


class EmptyRetrievalService:
    async def retrieve(self, **kwargs):
        return SimpleNamespace(sources=[], query_embedding=[], grounded_document_ids=[])


class StaticRetrievalService:
    def __init__(
        self,
        sources: list[ChatSource],
        grounded_document_ids: list[UUID] | None = None,
    ) -> None:
        self.sources = sources
        self.grounded_document_ids = grounded_document_ids or [
            UUID(str(source.document_id)) for source in sources
        ]
        self.calls: list[dict] = []

    async def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            sources=self.sources,
            query_embedding=[0.1, 0.2],
            grounded_document_ids=self.grounded_document_ids,
        )


class GuardLLMClient:
    def __init__(self) -> None:
        self.called = False

    async def generate(self, prompt: str) -> str:
        self.called = True
        raise AssertionError("generate should not be called")


class EmptyLLMClient:
    async def generate(self, prompt: str) -> str:
        return "   "


class CitationLLMClient:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    async def generate(self, prompt: str) -> str:
        return self.answer


class PromptAssertingLLMClient:
    def __init__(
        self,
        *,
        expected_text: str,
        answer: str,
        forbidden_text: str | None = None,
    ) -> None:
        self.expected_text = expected_text
        self.answer = answer
        self.forbidden_text = forbidden_text

    async def generate(self, prompt: str) -> str:
        assert self.expected_text in prompt
        if self.forbidden_text is not None:
            assert self.forbidden_text not in prompt
        return self.answer


class FakeAuditService:
    def __init__(self) -> None:
        self.entries: list[dict[str, str | None]] = []

    async def log(self, **kwargs):
        self.entries.append(kwargs)
        return SimpleNamespace(**kwargs)


def _build_service(
    *,
    retrieval_service,
    llm_client,
    existing_session: ChatSession | None = None,
    existing_messages: list[ChatMessage] | None = None,
) -> tuple[ChatService, FakeAsyncSession, FakeChatSessionRepository, FakeChatMessageRepository]:
    session = FakeAsyncSession()
    service = ChatService(
        session=session,
        retrieval_service=retrieval_service,
        llm_client=llm_client,
    )
    session_repo = FakeChatSessionRepository(existing=existing_session)
    message_repo = FakeChatMessageRepository(items=existing_messages)
    service.session_repo = session_repo
    service.message_repo = message_repo
    service.audit = FakeAuditService()
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
    assert response.active_context_document_ids == [str(sources[0].document_id)]
    assert response.active_context_documents == [
        {
            "document_id": str(sources[0].document_id),
            "file_name": "policy.md",
            "file_path": "/docs/policy.md",
        }
    ]
    assert "language model returned an empty response" in response.answer
    assert existing_session.updated_at is not None
    assert existing_session.updated_at > old_updated_at
    assert session.commits == 2


@pytest.mark.asyncio
async def test_chat_service_keeps_only_cited_sources_and_reindexes_citations() -> None:
    user = _build_user()
    sources = [
        ChatSource(
            chunk_id=uuid4(),
            document_id=uuid4(),
            file_name="manual.md",
            file_path="/docs/manual.md",
            page_number=None,
            section_title="Overview",
            snippet="General setup instructions.",
            distance=0.2,
            score=0.8,
        ),
        ChatSource(
            chunk_id=uuid4(),
            document_id=uuid4(),
            file_name="policy.md",
            file_path="/docs/policy.md",
            page_number=None,
            section_title="Carry Over",
            snippet="Employees can carry over five unused vacation days.",
            distance=0.08,
            score=0.96,
        ),
        ChatSource(
            chunk_id=uuid4(),
            document_id=uuid4(),
            file_name="faq.md",
            file_path="/docs/faq.md",
            page_number=None,
            section_title="FAQ",
            snippet="Shared storage quotas are reviewed weekly.",
            distance=0.18,
            score=0.82,
        ),
    ]
    service, session, session_repo, message_repo = _build_service(
        retrieval_service=StaticRetrievalService(sources),
        llm_client=CitationLLMClient(
            "Employees can carry over five unused vacation days [2]."
        ),
    )

    response = await service.ask(
        user=user,
        auth=_build_auth(user),
        request=ChatAskRequest(question="How many vacation days can employees carry over?"),
    )

    assert len(session_repo.items) == 1
    assert len(message_repo.items) == 2
    assert response.answer == "Employees can carry over five unused vacation days [1]."
    assert [source.file_name for source in response.sources] == ["policy.md"]
    assert response.active_context_document_ids == [str(sources[1].document_id)]
    assert response.active_context_documents == [
        {
            "document_id": str(sources[1].document_id),
            "file_name": "policy.md",
            "file_path": "/docs/policy.md",
        }
    ]
    assert message_repo.items[1].citations_json is not None
    assert len(message_repo.items[1].citations_json) == 1
    assert message_repo.items[1].citations_json[0]["file_name"] == "policy.md"
    assert session.commits == 2


@pytest.mark.asyncio
async def test_chat_service_uses_full_chunk_content_for_grounding_and_support_checks() -> None:
    user = _build_user()
    full_chunk_content = (
        "Ozgur Polat contact details and professional summary. "
        "Experienced Python Developer. "
        "Worked as a Data Analyst / Researcher at Selahaddin Eyyubi University "
        "from Mar 2014 to July 2016."
    )
    source = ChatSource(
        chunk_id=uuid4(),
        document_id=uuid4(),
        file_name="OzgurPolat_Resume.pdf",
        file_path="/docs/OzgurPolat_Resume.pdf",
        page_number=1,
        section_title=None,
        snippet="Ozgur Polat contact details and professional summary. Experienced Python Developer.",
        distance=0.07,
        score=0.97,
        content=full_chunk_content,
    )
    service, _, _, _ = _build_service(
        retrieval_service=StaticRetrievalService([source]),
        llm_client=PromptAssertingLLMClient(
            expected_text="Selahaddin Eyyubi University from Mar 2014 to July 2016.",
            answer="In 2016, Ozgur Polat worked at Selahaddin Eyyubi University [1].",
        ),
    )

    response = await service.ask(
        user=user,
        auth=_build_auth(user),
        request=ChatAskRequest(question="Where did Ozgur Polat work in 2016?"),
    )

    assert response.answer == "In 2016, Ozgur Polat worked at Selahaddin Eyyubi University [1]."
    assert len(response.sources) == 1
    assert response.sources[0].file_name == "OzgurPolat_Resume.pdf"


@pytest.mark.asyncio
async def test_chat_service_prefers_year_matching_sources_and_accepts_covering_ranges() -> None:
    user = _build_user()
    distracting_source = ChatSource(
        chunk_id=uuid4(),
        document_id=uuid4(),
        file_name="OzgurPolat_Resume.pdf",
        file_path="/docs/OzgurPolat_Resume.pdf",
        page_number=1,
        section_title=None,
        snippet="Python Developer FKS | Hasselt, Belgium | Jan 2023 - Feb 2025",
        distance=0.01,
        score=0.999,
        content="Python Developer FKS | Hasselt, Belgium | Jan 2023 - Feb 2025",
    )
    relevant_source = ChatSource(
        chunk_id=uuid4(),
        document_id=uuid4(),
        file_name="OzgurPolat_Resume.pdf",
        file_path="/docs/OzgurPolat_Resume.pdf",
        page_number=2,
        section_title=None,
        snippet="Data Analyst / Researcher Selahaddin Eyyubi University | Turkey | Mar 2014 - July 2016",
        distance=0.18,
        score=0.81,
        content="Data Analyst / Researcher Selahaddin Eyyubi University | Turkey | Mar 2014 - July 2016",
    )
    service, _, _, _ = _build_service(
        retrieval_service=StaticRetrievalService([distracting_source, relevant_source]),
        llm_client=PromptAssertingLLMClient(
            expected_text="Selahaddin Eyyubi University | Turkey | Mar 2014 - July 2016",
            forbidden_text="Python Developer FKS | Hasselt, Belgium | Jan 2023 - Feb 2025",
            answer="In 2015, Ozgur Polat worked at Selahaddin Eyyubi University [1].",
        ),
    )

    response = await service.ask(
        user=user,
        auth=_build_auth(user),
        request=ChatAskRequest(question="where did Ozgur polat work in 2015"),
    )

    assert response.answer == "In 2015, Ozgur Polat worked at Selahaddin Eyyubi University [1]."
    assert len(response.sources) == 1
    assert response.sources[0].page_number == 2


@pytest.mark.asyncio
async def test_chat_service_filters_education_entries_for_employment_questions() -> None:
    user = _build_user()
    education_source = ChatSource(
        chunk_id=uuid4(),
        document_id=uuid4(),
        file_name="OzgurPolat_Resume.pdf",
        file_path="/docs/OzgurPolat_Resume.pdf",
        page_number=3,
        section_title=None,
        snippet="Education & Qualifications Ataturk University, PhD in Economics (2005 - 2009)",
        distance=0.01,
        score=0.99,
        content="Education & Qualifications Ataturk University, PhD in Economics (2005 - 2009)",
    )
    employment_source = ChatSource(
        chunk_id=uuid4(),
        document_id=education_source.document_id,
        file_name="OzgurPolat_Resume.pdf",
        file_path="/docs/OzgurPolat_Resume.pdf",
        page_number=2,
        section_title=None,
        snippet="Data Analyst Turkish Statistical Office | Turkey | Nov 2004 - Mar 2010",
        distance=0.18,
        score=0.81,
        content="Data Analyst Turkish Statistical Office | Turkey | Nov 2004 - Mar 2010",
    )
    service, _, _, _ = _build_service(
        retrieval_service=StaticRetrievalService([education_source, employment_source]),
        llm_client=PromptAssertingLLMClient(
            expected_text="Data Analyst Turkish Statistical Office | Turkey | Nov 2004 - Mar 2010",
            forbidden_text="Education & Qualifications Ataturk University, PhD in Economics (2005 - 2009)",
            answer="In 2009, Ozgur Polat worked at the Turkish Statistical Office [1].",
        ),
    )

    response = await service.ask(
        user=user,
        auth=_build_auth(user),
        request=ChatAskRequest(question="where did Ozgur polat work in 2009"),
    )

    assert response.answer == "In 2009, Ozgur Polat worked at the Turkish Statistical Office [1]."
    assert len(response.sources) == 1
    assert response.sources[0].page_number == 2


@pytest.mark.asyncio
async def test_chat_service_anchors_follow_up_to_active_context_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _build_user()
    existing_session = ChatSession(
        id=uuid4(),
        user_id=user.id,
        title="Policy chat",
    )
    active_document_id = uuid4()
    retrieval_service = StaticRetrievalService(
        [
            ChatSource(
                chunk_id=uuid4(),
                document_id=active_document_id,
                file_name="policy.md",
                file_path="/docs/policy.md",
                page_number=None,
                section_title="Carry Over",
                snippet="Employees can carry over five unused vacation days.",
                distance=0.08,
                score=0.96,
            )
        ]
    )
    service, _, _, _ = _build_service(
        retrieval_service=retrieval_service,
        llm_client=CitationLLMClient("Employees can carry over five unused vacation days [1]."),
        existing_session=existing_session,
    )

    async def fake_build_retrieval_query(**kwargs):
        return "vacation policy carry over limit", True

    monkeypatch.setattr(
        "backend.services.chat_service.build_retrieval_query",
        fake_build_retrieval_query,
    )

    response = await service.ask(
        user=user,
        auth=_build_auth(user),
        request=ChatAskRequest(
            question="What about the carry over limit?",
            session_id=existing_session.id,
            active_context_document_ids=[str(active_document_id)],
        ),
    )

    assert len(retrieval_service.calls) == 1
    assert retrieval_service.calls[0]["document_ids"] == [active_document_id]
    assert retrieval_service.calls[0]["preferred_document_ids"] is None
    assert response.active_context_document_ids == [str(active_document_id)]
    assert response.active_context_documents == [
        {
            "document_id": str(active_document_id),
            "file_name": "policy.md",
            "file_path": "/docs/policy.md",
        }
    ]


@pytest.mark.asyncio
async def test_chat_service_deletes_owned_session() -> None:
    user = _build_user()
    existing_session = ChatSession(
        id=uuid4(),
        user_id=user.id,
        title="Disposable chat",
    )
    service, session, session_repo, _ = _build_service(
        retrieval_service=EmptyRetrievalService(),
        llm_client=EmptyLLMClient(),
        existing_session=existing_session,
    )

    await service.delete_session(str(existing_session.id), actor=user)

    assert session_repo.deleted_ids == [existing_session.id]
    assert len(service.audit.entries) == 1
    assert service.audit.entries[0]["action"] == "chat.deleted"
    assert service.audit.entries[0]["resource_id"] == str(existing_session.id)
    assert session.commits == 1
