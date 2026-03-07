from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.ai.embedding_client import DeterministicEmbeddingClient
from backend.db.models import Document
from backend.ingestion.pipeline import IngestionPipeline
from backend.parsers.document_parser import parse_document_bytes


@pytest.mark.asyncio
async def test_ingestion_pipeline_creates_chunks_with_embeddings() -> None:
    document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id='doc-1',
        file_path='/docs/handbook.txt',
        file_name='handbook.txt',
        allowed_user_ids=[],
        allowed_group_ids=[],
    )
    pipeline = IngestionPipeline(session=SimpleNamespace(), embedding_client=DeterministicEmbeddingClient(dim=32))
    captured: dict[str, object] = {}

    async def fake_replace_for_document(document_id: str, chunks):
        captured['document_id'] = document_id
        captured['chunks'] = chunks

    pipeline.chunk_repo = SimpleNamespace(replace_for_document=fake_replace_for_document)
    parsed = await parse_document_bytes('handbook.txt', 'text/plain', b'Alpha beta gamma delta epsilon ' * 80)

    chunks = await pipeline.ingest_document(document, parsed)

    assert captured['document_id'] == document.id
    assert len(chunks) >= 2
    assert all(chunk.embedding for chunk in chunks)
    assert document.parse_status == 'indexed'
