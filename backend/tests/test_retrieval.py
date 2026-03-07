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
        external_id='doc-1',
        file_path='/policies/leave.md',
        file_name='leave.md',
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=False,
    )
    hidden_document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id='doc-2',
        file_path='/deleted.md',
        file_name='deleted.md',
        allowed_user_ids=[],
        allowed_group_ids=[],
        is_deleted=True,
    )
    visible_chunk = DocumentChunk(
        id=uuid4(),
        document_id=visible_document.id,
        chunk_index=0,
        content='Employees receive 25 days of leave.',
    )
    visible_chunk.document = visible_document
    hidden_chunk = DocumentChunk(
        id=uuid4(),
        document_id=hidden_document.id,
        chunk_index=0,
        content='Old deleted content.',
    )
    hidden_chunk.document = hidden_document

    service = RetrievalService(session=SimpleNamespace())

    async def fake_semantic_search(**kwargs):
        return [(visible_chunk, 0.1), (hidden_chunk, 0.2)]

    service.chunk_repo = SimpleNamespace(semantic_search=fake_semantic_search)
    result = await service.retrieve(
        question='How much leave do employees receive?',
        auth=AuthContext(user_id='1', auth_provider='nextcloud', external_subject='alice', username='alice'),
        top_k=4,
    )

    assert len(result.sources) == 1
    assert result.sources[0].file_name == 'leave.md'
    assert result.sources[0].score > 0.9
