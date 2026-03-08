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
