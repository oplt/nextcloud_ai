from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.core.security import AuthContext
from backend.db.models import Document, DocumentChunk
from backend.services.retrieval_service import RetrievalService


@pytest.mark.asyncio
async def test_retrieval_formats_sources_and_skips_deleted_documents() -> None:
    visible_document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-1",
        file_path="/policies/leave.md",
        file_name="leave.md",
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=False,
    )
    hidden_document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-2",
        file_path="/deleted.md",
        file_name="deleted.md",
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=True,
    )
    visible_chunk = DocumentChunk(
        id=uuid4(),
        document_id=visible_document.id,
        chunk_index=0,
        content="Employees receive 25 days of leave.",
    )
    visible_chunk.document = visible_document
    hidden_chunk = DocumentChunk(
        id=uuid4(),
        document_id=hidden_document.id,
        chunk_index=0,
        content="Old deleted content.",
    )
    hidden_chunk.document = hidden_document

    service = RetrievalService(session=SimpleNamespace())

    async def fake_semantic_search(**kwargs):
        return [(visible_chunk, 0.1), (hidden_chunk, 0.2)]

    async def fake_keyword_search(**kwargs):
        return []

    service.chunk_repo = SimpleNamespace(
        semantic_search=fake_semantic_search,
        keyword_search=fake_keyword_search,
    )
    result = await service.retrieve(
        question="How much leave do employees receive?",
        auth=AuthContext(
            user_id="1",
            auth_provider="nextcloud",
            external_subject="alice",
            username="alice",
        ),
        top_k=4,
    )

    assert len(result.sources) == 1
    assert result.sources[0].file_name == "leave.md"
    assert result.sources[0].score > 0.9


@pytest.mark.asyncio
async def test_retrieval_keyword_search_can_override_bad_semantic_matches() -> None:
    relevant_document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-1",
        file_path="/Documents/OzgurPolat_Resume.pdf",
        file_name="OzgurPolat_Resume.pdf",
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=False,
    )
    irrelevant_document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-2",
        file_path="/Nextcloud Manual.pdf",
        file_name="Nextcloud Manual.pdf",
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=False,
    )
    relevant_chunk = DocumentChunk(
        id=uuid4(),
        document_id=relevant_document.id,
        chunk_index=0,
        content="Ozgur Polat worked as a Data Analyst / Researcher at Selahaddin Eyyubi University from Mar 2014 to July 2016.",
    )
    relevant_chunk.document = relevant_document
    irrelevant_chunk = DocumentChunk(
        id=uuid4(),
        document_id=irrelevant_document.id,
        chunk_index=0,
        content="Nextcloud user manual and synchronizing clients.",
    )
    irrelevant_chunk.document = irrelevant_document

    service = RetrievalService(session=SimpleNamespace())

    async def fake_semantic_search(**kwargs):
        return [(irrelevant_chunk, 0.1)]

    async def fake_keyword_search(**kwargs):
        return [relevant_chunk]

    service.chunk_repo = SimpleNamespace(
        semantic_search=fake_semantic_search,
        keyword_search=fake_keyword_search,
    )
    result = await service.retrieve(
        question="where did Ozgur Polat work between 2011 and 2016",
        auth=AuthContext(
            user_id="1",
            auth_provider="nextcloud",
            external_subject="alice",
            username="alice",
        ),
        top_k=4,
    )

    assert len(result.sources) == 1
    assert result.sources[0].file_name == "OzgurPolat_Resume.pdf"
    assert "Selahaddin Eyyubi University" in result.sources[0].snippet


@pytest.mark.asyncio
async def test_retrieval_preserves_full_chunk_content_for_grounding() -> None:
    document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-1",
        file_path="/Documents/OzgurPolat_Resume.pdf",
        file_name="OzgurPolat_Resume.pdf",
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=False,
    )
    long_prefix = "Ozgur Polat contact details and professional summary. " * 12
    full_content = (
        f"{long_prefix}Worked as a Data Analyst / Researcher at "
        "Selahaddin Eyyubi University from Mar 2014 to July 2016."
    )
    chunk = DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        chunk_index=0,
        content=full_content,
    )
    chunk.document = document

    service = RetrievalService(session=SimpleNamespace())

    async def fake_semantic_search(**kwargs):
        return [(chunk, 0.05)]

    async def fake_keyword_search(**kwargs):
        return [chunk]

    service.chunk_repo = SimpleNamespace(
        semantic_search=fake_semantic_search,
        keyword_search=fake_keyword_search,
    )
    result = await service.retrieve(
        question="Where did Ozgur Polat work in 2016?",
        auth=AuthContext(
            user_id="1",
            auth_provider="nextcloud",
            external_subject="alice",
            username="alice",
        ),
        top_k=4,
    )

    assert len(result.sources) == 1
    assert result.sources[0].snippet != full_content
    assert result.sources[0].content == full_content


@pytest.mark.asyncio
async def test_retrieval_boosts_employment_ranges_over_education_for_work_questions() -> None:
    document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-1",
        file_path="/Documents/OzgurPolat_Resume.pdf",
        file_name="OzgurPolat_Resume.pdf",
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=False,
    )
    profile_chunk = DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        chunk_index=0,
        content="Ozgur Polat Work Experience / Employment History Python Developer FKS | Hasselt | Jan 2023 - Feb 2025",
    )
    profile_chunk.document = document
    employment_chunk = DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        chunk_index=1,
        content="Data Analyst Turkish Statistical Office | Turkey | Nov 2004 - Mar 2010",
    )
    employment_chunk.document = document
    education_chunk = DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        chunk_index=2,
        content="Education & Qualifications Ataturk University, PhD in Economics (2005 - 2009)",
    )
    education_chunk.document = document

    service = RetrievalService(session=SimpleNamespace())

    async def fake_semantic_search(**kwargs):
        return [
            (profile_chunk, 0.01),
            (education_chunk, 0.02),
            (employment_chunk, 0.6),
        ]

    async def fake_keyword_search(**kwargs):
        return [profile_chunk, education_chunk, employment_chunk]

    service.chunk_repo = SimpleNamespace(
        semantic_search=fake_semantic_search,
        keyword_search=fake_keyword_search,
    )
    result = await service.retrieve(
        question="where did Ozgur polat work in 2009",
        auth=AuthContext(
            user_id="1",
            auth_provider="nextcloud",
            external_subject="alice",
            username="alice",
        ),
        top_k=4,
    )

    assert len(result.sources) >= 1
    assert result.sources[0].snippet.startswith("Data Analyst Turkish Statistical Office")


@pytest.mark.asyncio
async def test_retrieval_keeps_same_document_context_for_relative_employment_follow_up() -> None:
    document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-1",
        file_path="/Documents/OzgurPolat_Resume.pdf",
        file_name="OzgurPolat_Resume.pdf",
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=False,
    )
    first_role_chunk = DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        chunk_index=0,
        content="Data Analyst Turkish Statistical Office | Turkey | Nov 2004 - Mar 2010",
    )
    first_role_chunk.document = document
    next_role_chunk = DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        chunk_index=1,
        content="Assistant Professor Ataturk University | Turkey | Apr 2010 - Feb 2014",
    )
    next_role_chunk.document = document
    later_role_chunk = DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        chunk_index=2,
        content="Data Analyst / Researcher Selahaddin Eyyubi University | Turkey | Mar 2014 - July 2016",
    )
    later_role_chunk.document = document

    async def fake_embed_query(question: str) -> list[float]:
        return [0.1, 0.2]

    async def fake_semantic_search(**kwargs):
        assert kwargs["document_ids"] == [document.id]
        return [
            (first_role_chunk, 0.05),
            (next_role_chunk, 0.41),
            (later_role_chunk, 0.46),
        ]

    async def fake_keyword_search(**kwargs):
        assert kwargs["document_ids"] == [document.id]
        return [first_role_chunk]

    service = RetrievalService(
        session=SimpleNamespace(),
        embedding_client=SimpleNamespace(embed_query=fake_embed_query),
    )
    service.chunk_repo = SimpleNamespace(
        semantic_search=fake_semantic_search,
        keyword_search=fake_keyword_search,
    )

    result = await service.retrieve(
        question="Where did Ozgur Polat work after Turkish Statistical Office?",
        auth=AuthContext(
            user_id="1",
            auth_provider="nextcloud",
            external_subject="alice",
            username="alice",
        ),
        top_k=4,
        preferred_document_ids=[document.id],
    )

    snippets = [source.snippet for source in result.sources]

    assert any("Turkish Statistical Office" in snippet for snippet in snippets)
    assert any("Ataturk University" in snippet for snippet in snippets)


@pytest.mark.asyncio
async def test_retrieval_returns_one_source_per_document() -> None:
    handbook = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-1",
        file_path="/policies/handbook.md",
        file_name="handbook.md",
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=False,
    )
    first_chunk = DocumentChunk(
        id=uuid4(),
        document_id=handbook.id,
        chunk_index=0,
        content="Employees receive 25 days of leave and 10 days of sick leave.",
    )
    first_chunk.document = handbook
    second_chunk = DocumentChunk(
        id=uuid4(),
        document_id=handbook.id,
        chunk_index=1,
        content="The leave policy also describes carry-over rules and holiday schedules.",
    )
    second_chunk.document = handbook

    service = RetrievalService(session=SimpleNamespace())

    async def fake_semantic_search(**kwargs):
        return [(first_chunk, 0.08), (second_chunk, 0.09)]

    async def fake_keyword_search(**kwargs):
        return [first_chunk, second_chunk]

    service.chunk_repo = SimpleNamespace(
        semantic_search=fake_semantic_search,
        keyword_search=fake_keyword_search,
    )
    result = await service.retrieve(
        question="How much leave do employees receive?",
        auth=AuthContext(
            user_id="1",
            auth_provider="nextcloud",
            external_subject="alice",
            username="alice",
        ),
        top_k=4,
    )

    assert len(result.sources) == 1
    assert result.sources[0].file_name == "handbook.md"


@pytest.mark.asyncio
async def test_retrieval_drops_semantic_tail_documents_when_top_match_is_clear() -> None:
    policy = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-1",
        file_path="/policies/vacation.md",
        file_name="vacation.md",
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=False,
    )
    manual = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-2",
        file_path="/manuals/desktop-client.md",
        file_name="desktop-client.md",
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=False,
    )
    faq = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-3",
        file_path="/faq/storage.md",
        file_name="storage.md",
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=False,
    )

    policy_chunk = DocumentChunk(
        id=uuid4(),
        document_id=policy.id,
        chunk_index=0,
        content="Employees can carry over five unused vacation days into the next year with manager approval.",
    )
    policy_chunk.document = policy
    manual_chunk = DocumentChunk(
        id=uuid4(),
        document_id=manual.id,
        chunk_index=0,
        content="Desktop client setup instructions for Windows and macOS.",
    )
    manual_chunk.document = manual
    faq_chunk = DocumentChunk(
        id=uuid4(),
        document_id=faq.id,
        chunk_index=0,
        content="Storage quotas are enforced weekly for shared folders.",
    )
    faq_chunk.document = faq

    service = RetrievalService(session=SimpleNamespace())

    async def fake_semantic_search(**kwargs):
        return [
            (policy_chunk, 0.05),
            (manual_chunk, 0.26),
            (faq_chunk, 0.31),
        ]

    async def fake_keyword_search(**kwargs):
        return []

    service.chunk_repo = SimpleNamespace(
        semantic_search=fake_semantic_search,
        keyword_search=fake_keyword_search,
    )
    result = await service.retrieve(
        question="What is the vacation carry over policy?",
        auth=AuthContext(
            user_id="1",
            auth_provider="nextcloud",
            external_subject="alice",
            username="alice",
        ),
        top_k=4,
    )

    assert len(result.sources) == 1
    assert result.sources[0].file_name == "vacation.md"


@pytest.mark.asyncio
async def test_retrieval_keeps_close_semantic_matches_from_multiple_documents() -> None:
    policy = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-1",
        file_path="/policies/leave.md",
        file_name="leave.md",
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=False,
    )
    handbook = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-2",
        file_path="/handbook/time-off.md",
        file_name="time-off.md",
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=False,
    )

    policy_chunk = DocumentChunk(
        id=uuid4(),
        document_id=policy.id,
        chunk_index=0,
        content="Annual leave is 25 days per year for full-time employees.",
    )
    policy_chunk.document = policy
    handbook_chunk = DocumentChunk(
        id=uuid4(),
        document_id=handbook.id,
        chunk_index=0,
        content="The employee handbook confirms 25 days of annual leave and explains time-off approvals.",
    )
    handbook_chunk.document = handbook

    service = RetrievalService(session=SimpleNamespace())

    async def fake_semantic_search(**kwargs):
        return [
            (policy_chunk, 0.08),
            (handbook_chunk, 0.11),
        ]

    async def fake_keyword_search(**kwargs):
        return []

    service.chunk_repo = SimpleNamespace(
        semantic_search=fake_semantic_search,
        keyword_search=fake_keyword_search,
    )
    result = await service.retrieve(
        question="How many annual leave days do employees get?",
        auth=AuthContext(
            user_id="1",
            auth_provider="nextcloud",
            external_subject="alice",
            username="alice",
        ),
        top_k=4,
    )

    assert len(result.sources) == 2
    assert {source.file_name for source in result.sources} == {"leave.md", "time-off.md"}


@pytest.mark.asyncio
async def test_retrieval_expands_document_scope_with_graph_related_documents() -> None:
    primary_document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-1",
        file_path="/contracts/master-services-agreement.pdf",
        file_name="master-services-agreement.pdf",
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=False,
    )
    related_document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-2",
        file_path="/emails/vendor-renewal.eml",
        file_name="vendor-renewal.eml",
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=False,
    )
    related_chunk = DocumentChunk(
        id=uuid4(),
        document_id=related_document.id,
        chunk_index=0,
        content="Vendor confirmed the renewal deadline is 2026-06-30 and requested legal review.",
    )
    related_chunk.document = related_document

    service = RetrievalService(session=SimpleNamespace())
    service.graph_repo = SimpleNamespace(
        list_related_document_ids=_async_value([related_document.id])
    )

    async def fake_semantic_search(**kwargs):
        assert kwargs["document_ids"] == [primary_document.id, related_document.id]
        return [(related_chunk, 0.08)]

    async def fake_keyword_search(**kwargs):
        assert kwargs["document_ids"] == [primary_document.id, related_document.id]
        return []

    service.chunk_repo = SimpleNamespace(
        semantic_search=fake_semantic_search,
        keyword_search=fake_keyword_search,
    )

    result = await service.retrieve(
        question="What is the renewal deadline?",
        auth=AuthContext(
            user_id="1",
            auth_provider="nextcloud",
            external_subject="alice",
            username="alice",
        ),
        top_k=4,
        preferred_document_ids=[primary_document.id],
    )

    assert len(result.sources) == 1
    assert result.sources[0].file_name == "vendor-renewal.eml"


def _async_value(value):
    async def inner(**kwargs):
        return value

    return inner
