"""Phase 5: DB-backed retrieval workload benchmark (not fixture-only).

Seeds the eval fixture corpus into disposable Postgres/pgvector, runs
authorized RetrievalService iterations, and reports p50/p95/p99 latency,
event-loop lag, SQL statement/row/connection counts, memory, cache hit
rates, model-load counts, and authorized Recall@k.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import resource
import sys
import time
import tracemalloc
from typing import Any
from uuid import UUID

from backend.core.ai_resources import start_ai_resources, stop_ai_resources
from backend.core.async_cache import AsyncTTLCache
from backend.core.config import settings
from backend.evals.fixture_loader import (
    load_fixture_bundle,
    resolve_ids,
    seed_database_fixture,
)
from backend.evals.run_offline_eval import (
    EXIT_APP,
    EXIT_INFRA,
    EXIT_OK,
    InfrastructureError,
    _DatabaseMetrics,
    _aggregate,
    _auth_for_identity,
    _default_identity,
    _percentile,
    _score_case,
)


async def _event_loop_lag_samples(count: int = 30) -> list[float]:
    """Measure scheduling delay beyond an awaited sleep(0)."""
    samples: list[float] = []
    loop = asyncio.get_running_loop()
    for _ in range(count):
        started = time.perf_counter()
        future: asyncio.Future[float] = loop.create_future()

        def _mark(fut: asyncio.Future[float] = future) -> None:
            if not fut.done():
                fut.set_result(time.perf_counter())

        loop.call_soon(_mark)
        finished = await future
        samples.append(max(0.0, finished - started))
        await asyncio.sleep(0)
    return samples


async def _run_db_benchmark(*, iterations: int, top_k: int) -> dict[str, Any]:
    from backend.ai.embedding_client import DeterministicEmbeddingClient
    from backend.db.session import AsyncSessionLocal, dispose_db
    from backend.services.retrieval_service import RetrievalService

    database_url = settings.DATABASE_URL.lower()
    if settings.APP_ENV not in {"development", "test"} or not any(
        host in database_url for host in ("localhost", "127.0.0.1")
    ):
        raise InfrastructureError(
            "phase5 DB benchmark requires a local development/test database"
        )

    bundle = load_fixture_bundle()
    await start_ai_resources(role="api")
    cache = AsyncTTLCache(ttl_seconds=60, max_entries=128)
    model_loads = 0
    embedding_client = DeterministicEmbeddingClient()
    model_loads += 1

    iteration_seconds: list[float] = []
    retrieval_seconds: list[float] = []
    all_records: list[dict[str, Any]] = []
    db_metrics = _DatabaseMetrics()
    lag_samples: list[float] = []

    tracemalloc.start()
    wall_started = time.perf_counter()
    try:
        async with AsyncSessionLocal() as session:
            db_metrics.attach(session)
            await seed_database_fixture(session, bundle)
            svc = RetrievalService(session, embedding_client=embedding_client)

            for _ in range(iterations):
                iter_started = time.perf_counter()
                lag_samples.extend(await _event_loop_lag_samples(4))
                for row in bundle.gold:
                    identity = _default_identity(bundle, row)
                    auth = _auth_for_identity(identity)
                    request_scope = [
                        UUID(x) for x in resolve_ids(row.request_document_ids)
                    ]
                    cache_key = f"{identity.key}:{row.id}:{top_k}"

                    async def _retrieve(
                        *,
                        _row=row,
                        _auth=auth,
                        _scope=request_scope,
                    ):
                        started = time.perf_counter()
                        result = await svc.retrieve(
                            question=_row.question,
                            auth=_auth,
                            top_k=top_k,
                            document_ids=_scope or None,
                        )
                        retrieval_seconds.append(time.perf_counter() - started)
                        return result

                    res = await cache.get_or_set(cache_key, _retrieve)
                    all_records.append(
                        _score_case(
                            row=row,
                            expected_doc_ids=resolve_ids(row.expected_document_ids),
                            expected_chunk_ids=resolve_ids(row.expected_chunk_ids),
                            retrieved_doc_ids=[
                                str(source.document_id) for source in res.sources
                            ],
                            retrieved_chunk_ids=[
                                str(source.chunk_id) for source in res.sources
                            ],
                            cited_doc_ids=[],
                            answer_text=None,
                            mode="retrieval",
                            stage_latency={},
                            extra={"identity": identity.key},
                        )
                    )
                iteration_seconds.append(time.perf_counter() - iter_started)
            await session.rollback()
            db_metrics.detach()
    finally:
        elapsed = time.perf_counter() - wall_started
        _current, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        await stop_ai_resources()
        await dispose_db()

    iteration_seconds.sort()
    retrieval_seconds.sort()
    lag_samples.sort()
    aggregate = _aggregate(all_records)
    cache_stats = cache.stats
    hit_rate = (
        cache_stats["hits"] / (cache_stats["hits"] + cache_stats["misses"])
        if (cache_stats["hits"] + cache_stats["misses"])
        else 0.0
    )
    return {
        "ok": True,
        "mode": "db_retrieval",
        "iterations": iterations,
        "cases": len(all_records),
        "elapsed_seconds": elapsed,
        "throughput_cases_per_second": (len(all_records) / elapsed if elapsed else 0.0),
        "iteration_latency_seconds": {
            "p50": _percentile(iteration_seconds, 0.50),
            "p95": _percentile(iteration_seconds, 0.95),
            "p99": _percentile(iteration_seconds, 0.99),
        },
        "retrieval_latency_seconds": {
            "p50": _percentile(retrieval_seconds, 0.50),
            "p95": _percentile(retrieval_seconds, 0.95),
            "p99": _percentile(retrieval_seconds, 0.99),
        },
        "event_loop_lag_seconds": {
            "p50": _percentile(lag_samples, 0.50),
            "p95": _percentile(lag_samples, 0.95),
            "p99": _percentile(lag_samples, 0.99),
            "samples": len(lag_samples),
        },
        "python_peak_memory_bytes": peak_bytes,
        "process_max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "authorized_recall_at_6": aggregate["means"].get("recall@6"),
        "authorized_mrr": aggregate["means"].get("mrr"),
        "database_metrics": db_metrics.as_dict(),
        "model_loads": model_loads,
        "cache": {**cache_stats, "hit_rate": hit_rate},
        "notes": [
            "Uses disposable/local Postgres with seeded fixtures + deterministic embeddings.",
            "Cache warms after the first iteration; hit_rate reflects repeated gold questions.",
            "Does not claim hardware-specific capacity targets.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=6)
    args = parser.parse_args(argv)
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")
    try:
        report = asyncio.run(
            _run_db_benchmark(iterations=args.iterations, top_k=args.top_k)
        )
    except InfrastructureError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_class": "infrastructure",
                    "error": str(exc),
                    "hint": "Run via make phase5-db-benchmark (starts disposable PG).",
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
