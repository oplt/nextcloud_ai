from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.ai.embedding_client import DeterministicEmbeddingClient
from backend.db.models import Document
from backend.ingestion.pipeline import IngestionPipeline
from backend.parsers.document_parser import parse_document_bytes
from backend.services.indexing_service import DocumentIngestionService


@pytest.mark.asyncio
async def test_ingestion_pipeline_creates_chunks_with_embeddings() -> None:
    document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-1",
        file_path="/docs/handbook.txt",
        file_name="handbook.txt",
        allowed_user_ids=[],
        allowed_group_ids=[],
    )
    pipeline = IngestionPipeline(
        session=SimpleNamespace(), embedding_client=DeterministicEmbeddingClient(dim=32)
    )
    captured: dict[str, object] = {}

    async def fake_replace_for_document(document_id: str, chunks):
        captured["document_id"] = document_id
        captured["chunks"] = chunks

    pipeline.chunk_repo = SimpleNamespace(
        replace_for_document=fake_replace_for_document
    )
    parsed = await parse_document_bytes(
        "handbook.txt", "text/plain", b"Alpha beta gamma delta epsilon " * 80
    )

    chunks = await pipeline.ingest_document(document, parsed)

    assert captured["document_id"] == document.id
    assert len(chunks) >= 2
    assert all(chunk.embedding for chunk in chunks)
    assert document.parse_status == "indexed"


@pytest.mark.asyncio
async def test_ingestion_clears_stale_chunks_for_unsupported_files() -> None:
    document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-unsupported",
        file_path="/docs/archive.bin",
        file_name="archive.bin",
        mime_type="application/x-custom-binary",
        indexed_at=datetime.now(timezone.utc),
        parse_status="indexed",
        allowed_user_ids=[],
        allowed_group_ids=[],
    )
    deleted: list[str] = []
    service = DocumentIngestionService(session=SimpleNamespace(flush=_noop))
    service.chunk_repo = SimpleNamespace(
        delete_for_document=lambda document_id: _record_delete(deleted, document_id)
    )

    result = await service.ingest_document_bytes(document, b"\x00\x01\x02")

    assert result is document
    assert deleted == [str(document.id)]
    assert document.parse_status == "unsupported"
    assert document.indexed_at is None


@pytest.mark.asyncio
async def test_ingestion_clears_stale_chunks_when_pipeline_fails() -> None:
    document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-failure",
        file_path="/docs/handbook.txt",
        file_name="handbook.txt",
        mime_type="text/plain",
        indexed_at=datetime.now(timezone.utc),
        parse_status="indexed",
        allowed_user_ids=[],
        allowed_group_ids=[],
    )
    deleted: list[str] = []
    service = DocumentIngestionService(session=SimpleNamespace(flush=_noop))
    service.chunk_repo = SimpleNamespace(
        delete_for_document=lambda document_id: _record_delete(deleted, document_id)
    )
    service.pipeline = SimpleNamespace(ingest_document=_raise_ingestion_failure)

    with pytest.raises(RuntimeError, match="embedding backend unavailable"):
        await service.ingest_document_bytes(document, b"alpha beta gamma")

    assert deleted == [str(document.id)]
    assert document.parse_status == "failed"
    assert document.indexed_at is None
    assert document.parse_error == "embedding backend unavailable"


async def _record_delete(store: list[str], document_id) -> int:
    store.append(str(document_id))
    return 1


async def _raise_ingestion_failure(*args, **kwargs) -> None:
    raise RuntimeError("embedding backend unavailable")


async def _noop() -> None:
    return None
