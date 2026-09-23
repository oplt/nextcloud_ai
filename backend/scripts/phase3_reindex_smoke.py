"""Phase 3: staged reindex promote + rollback on disposable Postgres.

Builds a published generation, prepares a replacement generation, compares
authorized lexical recall, atomically promotes, then rolls back and proves the
previous generation content is restored.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text

from backend.db.models import Connector, Document, DocumentChunk
from backend.db.repo.document import DocumentChunkRepository
from backend.db.session import AsyncSessionLocal, dispose_db
from backend.ingestion.index_versions import (
    begin_index_attempt,
    mark_published,
)


@dataclass(slots=True)
class ChunkSnapshot:
    chunk_index: int
    content: str
    content_hash: str | None
    metadata_json: dict[str, Any] | None


def _snapshot(chunks: list[DocumentChunk]) -> list[ChunkSnapshot]:
    return [
        ChunkSnapshot(
            chunk_index=int(chunk.chunk_index),
            content=str(chunk.content),
            content_hash=chunk.content_hash,
            metadata_json=dict(chunk.metadata_json or {}),
        )
        for chunk in sorted(chunks, key=lambda item: item.chunk_index)
    ]


def _recall(chunks: list[ChunkSnapshot], needle: str) -> float:
    if not chunks:
        return 0.0
    hits = sum(1 for chunk in chunks if needle in chunk.content)
    return hits / len(chunks)


async def _seed() -> uuid.UUID:
    async with AsyncSessionLocal() as session:
        connector = Connector(
            connector_type="nextcloud",
            display_name="phase3-reindex",
            base_url="https://nc.example",
            username="phase3",
            encrypted_secret="unused",
            root_path="/",
            is_active=True,
            status="ready",
        )
        session.add(connector)
        await session.flush()
        document = Document(
            connector_id=connector.id,
            external_id=f"phase3-{uuid.uuid4()}",
            file_path="/phase3/reindex.txt",
            file_name="reindex.txt",
            source_type="nextcloud",
            sync_status="synced",
            parse_status="indexed",
            index_generation=0,
            published_generation=0,
            version_tag="v1",
            allowed_user_ids=["phase3-user"],
            allowed_group_ids=[],
            owner_external_id="phase3-user",
        )
        session.add(document)
        await session.flush()

        attempt = await begin_index_attempt(session, document)
        gen1_chunks = [
            DocumentChunk(
                document_id=document.id,
                chunk_index=0,
                content="GEN1 alpha invoice EUR 42 unique-token-alpha",
                token_count=6,
                content_hash="gen1-a",
                chunk_type="text",
                embedding_status="ready",
                metadata_json={"generation": attempt.generation},
            ),
            DocumentChunk(
                document_id=document.id,
                chunk_index=1,
                content="GEN1 beta lunch noon unique-token-beta",
                token_count=5,
                content_hash="gen1-b",
                chunk_type="text",
                embedding_status="ready",
                metadata_json={"generation": attempt.generation},
            ),
        ]
        repo = DocumentChunkRepository(session)
        await repo.replace_for_document(document.id, gen1_chunks)
        mark_published(document, attempt)
        await session.commit()
        return document.id


async def _load_chunks(document_id: uuid.UUID) -> list[DocumentChunk]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        return list(result.scalars().all())


async def _promote_replacement(
    document_id: uuid.UUID, *, previous: list[ChunkSnapshot]
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        document = await session.get(Document, document_id)
        assert document is not None
        prior_published = int(document.published_generation)
        attempt = await begin_index_attempt(session, document)
        gen2_chunks = [
            DocumentChunk(
                document_id=document.id,
                chunk_index=0,
                content="GEN2 gamma invoice EUR 99 unique-token-gamma",
                token_count=6,
                content_hash="gen2-a",
                chunk_type="text",
                embedding_status="ready",
                metadata_json={"generation": attempt.generation},
            ),
            DocumentChunk(
                document_id=document.id,
                chunk_index=1,
                content="GEN2 delta policy clause unique-token-delta",
                token_count=5,
                content_hash="gen2-b",
                chunk_type="text",
                embedding_status="ready",
                metadata_json={"generation": attempt.generation},
            ),
        ]
        # Compare authorized recall before promoting (side-by-side snapshots).
        candidate = _snapshot(gen2_chunks)
        recall_old_alpha = _recall(previous, "unique-token-alpha")
        recall_new_gamma = _recall(candidate, "unique-token-gamma")
        if recall_old_alpha <= 0 or recall_new_gamma <= 0:
            raise RuntimeError("pre-promote recall comparison failed")

        repo = DocumentChunkRepository(session)
        await repo.replace_for_document(document.id, gen2_chunks)
        mark_published(document, attempt)
        await session.commit()
        return {
            "prior_published": prior_published,
            "promoted_generation": attempt.generation,
            "recall_old_alpha": recall_old_alpha,
            "recall_new_gamma": recall_new_gamma,
        }


async def _rollback(
    document_id: uuid.UUID,
    *,
    previous: list[ChunkSnapshot],
    prior_published: int,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        document = await session.get(Document, document_id)
        assert document is not None
        restored = [
            DocumentChunk(
                document_id=document.id,
                chunk_index=snap.chunk_index,
                content=snap.content,
                token_count=len(snap.content.split()),
                content_hash=snap.content_hash,
                chunk_type="text",
                embedding_status="ready",
                metadata_json=snap.metadata_json,
            )
            for snap in previous
        ]
        repo = DocumentChunkRepository(session)
        await repo.replace_for_document(document.id, restored)
        document.published_generation = prior_published
        document.index_generation = max(
            int(document.index_generation or 0), prior_published
        )
        await session.commit()
        return {"rolled_back_to": prior_published}


async def _run() -> dict[str, Any]:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await session.commit()

        document_id = await _seed()
        gen1 = _snapshot(await _load_chunks(document_id))
        if _recall(gen1, "unique-token-alpha") <= 0:
            raise RuntimeError("gen1 missing alpha token")

        promote = await _promote_replacement(document_id, previous=gen1)
        gen2 = _snapshot(await _load_chunks(document_id))
        if _recall(gen2, "unique-token-gamma") <= 0:
            raise RuntimeError("promote did not publish gamma")
        if _recall(gen2, "unique-token-alpha") > 0:
            raise RuntimeError("promote left gen1 alpha content")

        rollback = await _rollback(
            document_id,
            previous=gen1,
            prior_published=int(promote["prior_published"]),
        )
        restored = _snapshot(await _load_chunks(document_id))
        if _recall(restored, "unique-token-alpha") <= 0:
            raise RuntimeError("rollback lost gen1 alpha")
        if _recall(restored, "unique-token-gamma") > 0:
            raise RuntimeError("rollback retained gen2 gamma")

        async with AsyncSessionLocal() as session:
            document = await session.get(Document, document_id)
            assert document is not None
            published = int(document.published_generation)

        return {
            "document_id": str(document_id),
            "promote": promote,
            "rollback": rollback,
            "final_published_generation": published,
            "restored_chunk_hashes": [snap.content_hash for snap in restored],
        }
    finally:
        await dispose_db()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        report = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **report}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
