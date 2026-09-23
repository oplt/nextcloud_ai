"""Phase 5: exact vs IVFFlat vs HNSW authorized ANN benchmark.

Builds a representative synthetic corpus on disposable Postgres/pgvector,
measures authorized top-k recall against an exact baseline, latency p50/p95/p99,
and process memory. IVFFlat probes and HNSW (m/ef_construction) are swept.
Does not claim a production speedup — reports measurements only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import resource
import sys
import time
import uuid
from typing import Any

from sqlalchemy import text

from backend.core.config import settings
from backend.core.security import AuthContext
from backend.db.models import Connector, Document, DocumentChunk
from backend.db.repo.document import DocumentChunkRepository
from backend.db.session import AsyncSessionLocal, dispose_db
from backend.evals.run_offline_eval import (
    EXIT_APP,
    EXIT_INFRA,
    EXIT_OK,
    InfrastructureError,
    _percentile,
)


def _unit_vector(seed: int, dim: int) -> list[float]:
    # Deterministic pseudo-random unit vector for reproducible ANN neighbors.
    values: list[float] = []
    state = seed * 1_000_003 + 17
    for i in range(dim):
        state = (1_103_515_245 * state + 12_345) & 0x7FFFFFFF
        values.append(
            ((state % 10_000) / 10_000.0) - 0.5 + (0.01 if i == seed % dim else 0.0)
        )
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def _recall_at_k(expected: list[str], got: list[str], k: int) -> float:
    if not expected:
        return 1.0
    top = set(expected[:k])
    hits = sum(1 for item in got[:k] if item in top)
    return hits / len(top)


async def _seed_corpus(
    *,
    corpus_size: int,
    dim: int,
    auth_user: str,
) -> tuple[list[uuid.UUID], list[list[float]], AuthContext]:
    async with AsyncSessionLocal() as session:
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connector = Connector(
            connector_type="nextcloud",
            display_name="phase5-ann",
            base_url="https://nc.example",
            username="phase5",
            encrypted_secret="unused",
            root_path="/",
            is_active=True,
            status="ready",
        )
        session.add(connector)
        await session.flush()

        chunk_ids: list[uuid.UUID] = []
        vectors: list[list[float]] = []
        for index in range(corpus_size):
            document = Document(
                connector_id=connector.id,
                external_id=f"ann-{index}",
                file_path=f"/ann/doc_{index}.txt",
                file_name=f"doc_{index}.txt",
                source_type="nextcloud",
                sync_status="synced",
                parse_status="indexed",
                index_generation=1,
                published_generation=1,
                version_tag="v1",
                allowed_user_ids=[auth_user],
                allowed_group_ids=[],
                owner_external_id=auth_user,
            )
            session.add(document)
            await session.flush()
            vector = _unit_vector(index + 1, dim)
            chunk = DocumentChunk(
                document_id=document.id,
                chunk_index=0,
                content=f"synthetic chunk {index} marker-{index}",
                token_count=4,
                content_hash=f"ann-{index}",
                chunk_type="text",
                embedding_status="ready",
                embedding=vector,
                metadata_json={"ann_seed": index},
            )
            session.add(chunk)
            await session.flush()
            chunk_ids.append(chunk.id)
            vectors.append(vector)
        await session.commit()

    auth = AuthContext(
        user_id=auth_user,
        auth_provider="local",
        username=auth_user,
        is_superuser=False,
    )
    return chunk_ids, vectors, auth


async def _ensure_ivfflat(*, lists: int) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DROP INDEX IF EXISTS ix_document_chunks_embedding_ann")
        )
        await session.execute(
            text("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
        )
        await session.execute(
            text(
                f"""
                CREATE INDEX ix_document_chunks_embedding_ann
                ON document_chunks
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = {int(lists)})
                """
            )
        )
        await session.execute(text("ANALYZE document_chunks"))
        await session.commit()


async def _ensure_hnsw(*, m: int, ef_construction: int) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DROP INDEX IF EXISTS ix_document_chunks_embedding_ann")
        )
        await session.execute(
            text("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
        )
        await session.execute(
            text(
                f"""
                CREATE INDEX ix_document_chunks_embedding_hnsw
                ON document_chunks
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = {int(m)}, ef_construction = {int(ef_construction)})
                """
            )
        )
        await session.execute(text("ANALYZE document_chunks"))
        await session.commit()


async def _drop_ann_indexes() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DROP INDEX IF EXISTS ix_document_chunks_embedding_ann")
        )
        await session.execute(
            text("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
        )
        await session.commit()


async def _search(
    *,
    auth: AuthContext,
    query: list[float],
    limit: int,
    mode: str,
    probes: int | None = None,
    ef_search: int | None = None,
) -> tuple[list[str], float]:
    async with AsyncSessionLocal() as session:
        previous_probes = int(settings.PGVECTOR_IVFFLAT_PROBES)
        try:
            if mode == "exact":
                # Disable ANN index use so cosine ordering is exact over the ACL set.
                await session.execute(text("SET LOCAL enable_indexscan = off"))
                await session.execute(text("SET LOCAL enable_bitmapscan = off"))
            elif mode == "ivfflat" and probes is not None:
                # semantic_search reads probes from settings for broad ANN.
                object.__setattr__(settings, "PGVECTOR_IVFFLAT_PROBES", int(probes))
            elif mode == "hnsw" and ef_search is not None:
                await session.execute(
                    text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}")
                )

            repo = DocumentChunkRepository(session)
            started = time.perf_counter()
            rows = await repo.semantic_search(
                embedding=query,
                auth=auth,
                limit=limit,
                document_ids=None,
            )
            ids = [str(chunk.id) for chunk, _ in rows]
            return ids, time.perf_counter() - started
        finally:
            object.__setattr__(settings, "PGVECTOR_IVFFLAT_PROBES", previous_probes)


async def _measure_mode(
    *,
    auth: AuthContext,
    chunk_ids: list[uuid.UUID],
    vectors: list[list[float]],
    query_count: int,
    top_k: int,
    mode: str,
    probes: int | None = None,
    ef_search: int | None = None,
) -> dict[str, Any]:
    latencies: list[float] = []
    recalls: list[float] = []
    # Exact gold for the first query_count vectors.
    gold: list[list[str]] = []
    for index in range(query_count):
        # Exact neighbors via the same cosine space (precomputed offline).
        query = vectors[index]
        scored = []
        for other_index, other in enumerate(vectors):
            # cosine distance = 1 - dot for unit vectors
            dist = 1.0 - sum(a * b for a, b in zip(query, other, strict=True))
            scored.append((dist, str(chunk_ids[other_index])))
        scored.sort(key=lambda item: item[0])
        gold.append([item[1] for item in scored[:top_k]])

    for index in range(query_count):
        ids, elapsed = await _search(
            auth=auth,
            query=vectors[index],
            limit=top_k,
            mode=mode,
            probes=probes,
            ef_search=ef_search,
        )
        latencies.append(elapsed)
        recalls.append(_recall_at_k(gold[index], ids, top_k))

    latencies.sort()
    return {
        "mode": mode,
        "probes": probes,
        "ef_search": ef_search,
        "queries": query_count,
        "authorized_recall_at_k": sum(recalls) / len(recalls) if recalls else 0.0,
        "latency_seconds": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
            "mean": sum(latencies) / len(latencies) if latencies else 0.0,
        },
    }


async def _run(
    *,
    corpus_size: int,
    query_count: int,
    top_k: int,
    lists: int,
) -> dict[str, Any]:
    database_url = settings.DATABASE_URL.lower()
    if settings.APP_ENV not in {"development", "test"} or not any(
        host in database_url for host in ("localhost", "127.0.0.1")
    ):
        raise InfrastructureError(
            "phase5 ANN benchmark requires a local development/test database"
        )

    dim = int(settings.EMBEDDING_DIM)
    auth_user = "phase5-ann-user"
    chunk_ids, vectors, auth = await _seed_corpus(
        corpus_size=corpus_size, dim=dim, auth_user=auth_user
    )

    results: list[dict[str, Any]] = []
    try:
        # Exact baseline (index scans disabled).
        await _drop_ann_indexes()
        results.append(
            await _measure_mode(
                auth=auth,
                chunk_ids=chunk_ids,
                vectors=vectors,
                query_count=query_count,
                top_k=top_k,
                mode="exact",
            )
        )

        await _ensure_ivfflat(lists=lists)
        for probes in (1, 5, 10, 20):
            if probes > lists:
                continue
            results.append(
                await _measure_mode(
                    auth=auth,
                    chunk_ids=chunk_ids,
                    vectors=vectors,
                    query_count=query_count,
                    top_k=top_k,
                    mode="ivfflat",
                    probes=probes,
                )
            )

        await _ensure_hnsw(m=16, ef_construction=64)
        for ef_search in (10, 40, 100):
            results.append(
                await _measure_mode(
                    auth=auth,
                    chunk_ids=chunk_ids,
                    vectors=vectors,
                    query_count=query_count,
                    top_k=top_k,
                    mode="hnsw",
                    ef_search=ef_search,
                )
            )
    finally:
        await dispose_db()

    exact = next(item for item in results if item["mode"] == "exact")
    return {
        "ok": True,
        "corpus_size": corpus_size,
        "dimension": dim,
        "top_k": top_k,
        "ivfflat_lists": lists,
        "process_max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "exact_baseline_recall_at_k": exact["authorized_recall_at_k"],
        "results": results,
        "recommendation": _recommend(results),
        "notes": [
            "Exact baseline disables index scans for distance ordering.",
            "IVFFlat lists chosen for the synthetic load; rebuild after real corpus growth.",
            "HNSW created only on disposable DB for measurement — not a schema migration.",
            "Do not swap production ANN strategy without reviewing these metrics on staging data.",
        ],
    }


def _recommend(results: list[dict[str, Any]]) -> dict[str, Any]:
    exact = next(item for item in results if item["mode"] == "exact")
    candidates = [
        item
        for item in results
        if item["mode"] != "exact"
        and item["authorized_recall_at_k"] >= exact["authorized_recall_at_k"] - 0.02
    ]
    if not candidates:
        return {
            "strategy": "exact",
            "reason": "No ANN config stayed within 2pp of exact authorized recall.",
        }
    best = min(candidates, key=lambda item: item["latency_seconds"]["p95"])
    return {
        "strategy": best["mode"],
        "probes": best.get("probes"),
        "ef_search": best.get("ef_search"),
        "reason": (
            f"{best['mode']} matched exact recall within 2pp with best p95 "
            f"({best['latency_seconds']['p95']:.6f}s) on this synthetic load."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-size", type=int, default=400)
    parser.add_argument("--queries", type=int, default=25)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--lists", type=int, default=40)
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(
            _run(
                corpus_size=args.corpus_size,
                query_count=min(args.queries, args.corpus_size),
                top_k=args.top_k,
                lists=args.lists,
            )
        )
    except InfrastructureError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_class": "infrastructure",
                    "error": str(exc),
                    "hint": "Run via make phase5-ann-benchmark",
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return EXIT_INFRA
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps({"ok": False, "error_class": "application", "error": str(exc)}),
            indent=2,
            file=sys.stderr,
        )
        return EXIT_APP
    print(json.dumps(report, indent=2, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
