"""Phase 5: concurrent capacity smoke across DB + cache + parse + embed paths.

Exercises overlapping RetrievalService, parse_document_bytes, deterministic
embedding, AsyncTTLCache, and bounded_work queues against disposable
Postgres. Optional live Ollama probe when OLLAMA_BASE_URL is reachable.
Reports success rates, latency percentiles, event-loop lag, and pool pressure
signals. Not a hardware capacity claim.

Each concurrent retrieval opens its own AsyncSession (never shared).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import resource
import sys
import time
from typing import Any
from uuid import UUID

import httpx

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
    _auth_for_identity,
    _default_identity,
    _percentile,
)
from backend.parsers.document_parser import parse_document_bytes
from backend.services.bounded_work import map_bounded


async def _event_loop_lag(count: int = 40) -> list[float]:
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


async def _probe_ollama(base_url: object) -> dict[str, Any]:
    url = str(base_url).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{url}/api/tags")
            response.raise_for_status()
            models = response.json().get("models") or []
            return {"reachable": True, "model_count": len(models), "base_url": url}
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "error": str(exc), "base_url": url}


async def _run(*, concurrency: int, rounds: int) -> dict[str, Any]:
    from backend.ai.embedding_client import DeterministicEmbeddingClient
    from backend.db.session import AsyncSessionLocal, dispose_db
    from backend.services.retrieval_service import RetrievalService

    database_url = settings.DATABASE_URL.lower()
    if settings.APP_ENV not in {"development", "test"} or not any(
        host in database_url for host in ("localhost", "127.0.0.1")
    ):
        raise InfrastructureError(
            "phase5 concurrency smoke requires a local development/test database"
        )

    bundle = load_fixture_bundle()
    embedding_client = DeterministicEmbeddingClient()
    cache = AsyncTTLCache(ttl_seconds=30, max_entries=64)

    retrieval_latencies: list[float] = []
    parse_latencies: list[float] = []
    embed_latencies: list[float] = []
    latency_lock = asyncio.Lock()
    errors: list[str] = []
    successes = {"retrieval": 0, "parse": 0, "embed": 0, "cache": 0}
    success_lock = asyncio.Lock()

    sample_bytes = b"Phase 5 concurrency parse sample.\nLine two.\n"
    gold = list(bundle.gold)

    # Seed once in a dedicated session, then run concurrent work.
    async with AsyncSessionLocal() as seed_session:
        await seed_database_fixture(seed_session, bundle)
        await seed_session.commit()

    wall_started = time.perf_counter()
    try:

        async def retrieval_job(index: int) -> None:
            row = gold[index % len(gold)]
            identity = _default_identity(bundle, row)
            auth = _auth_for_identity(identity)
            scope = [UUID(x) for x in resolve_ids(row.request_document_ids)]
            started = time.perf_counter()
            try:
                async with AsyncSessionLocal() as session:
                    svc = RetrievalService(session, embedding_client=embedding_client)
                    await svc.retrieve(
                        question=row.question,
                        auth=auth,
                        top_k=6,
                        document_ids=scope or None,
                    )
                async with latency_lock:
                    retrieval_latencies.append(time.perf_counter() - started)
                async with success_lock:
                    successes["retrieval"] += 1
            except Exception as exc:  # noqa: BLE001
                async with success_lock:
                    errors.append(f"retrieval:{exc}")

        async def parse_job(_index: int) -> None:
            started = time.perf_counter()
            try:
                await parse_document_bytes(
                    "phase5.txt",
                    "text/plain",
                    sample_bytes,
                )
                async with latency_lock:
                    parse_latencies.append(time.perf_counter() - started)
                async with success_lock:
                    successes["parse"] += 1
            except Exception as exc:  # noqa: BLE001
                async with success_lock:
                    errors.append(f"parse:{exc}")

        async def embed_job(index: int) -> None:
            started = time.perf_counter()
            try:
                await embedding_client.embed_documents(
                    [f"phase5 embed concurrency {index}"]
                )
                async with latency_lock:
                    embed_latencies.append(time.perf_counter() - started)
                async with success_lock:
                    successes["embed"] += 1
            except Exception as exc:  # noqa: BLE001
                async with success_lock:
                    errors.append(f"embed:{exc}")

        async def cache_job(index: int) -> None:
            async def factory() -> str:
                await asyncio.sleep(0.005)
                return f"value-{index % 8}"

            await cache.get_or_set(f"k-{index % 8}", factory)
            async with success_lock:
                successes["cache"] += 1

        for _round in range(rounds):
            jobs = list(range(concurrency))
            await asyncio.gather(
                map_bounded(jobs, retrieval_job, concurrency=concurrency),
                map_bounded(jobs, parse_job, concurrency=min(2, concurrency)),
                map_bounded(jobs, embed_job, concurrency=concurrency),
                map_bounded(jobs, cache_job, concurrency=concurrency),
            )

        lag_samples = await _event_loop_lag()
    finally:
        elapsed = time.perf_counter() - wall_started
        await dispose_db()

    ollama = await _probe_ollama(settings.OLLAMA_BASE_URL)
    total_jobs = concurrency * rounds
    retrieval_latencies.sort()
    parse_latencies.sort()
    embed_latencies.sort()
    lag_samples.sort()

    return {
        "ok": len(errors) == 0,
        "concurrency": concurrency,
        "rounds": rounds,
        "jobs_per_workload": total_jobs,
        "elapsed_seconds": elapsed,
        "successes": successes,
        "error_count": len(errors),
        "errors_sample": errors[:8],
        "retrieval_latency_seconds": {
            "p50": _percentile(retrieval_latencies, 0.50),
            "p95": _percentile(retrieval_latencies, 0.95),
            "p99": _percentile(retrieval_latencies, 0.99),
        },
        "parse_latency_seconds": {
            "p50": _percentile(parse_latencies, 0.50),
            "p95": _percentile(parse_latencies, 0.95),
            "p99": _percentile(parse_latencies, 0.99),
        },
        "embed_latency_seconds": {
            "p50": _percentile(embed_latencies, 0.50),
            "p95": _percentile(embed_latencies, 0.95),
            "p99": _percentile(embed_latencies, 0.99),
        },
        "event_loop_lag_seconds": {
            "p50": _percentile(lag_samples, 0.50),
            "p95": _percentile(lag_samples, 0.95),
            "p99": _percentile(lag_samples, 0.99),
        },
        "cache": cache.stats,
        "ollama": ollama,
        "process_max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "provider_budget_hints": {
            "NEXTCLOUD_SYNC_INGEST_CONCURRENCY": settings.NEXTCLOUD_SYNC_INGEST_CONCURRENCY,
            "note": (
                "In-process smoke with one AsyncSession per retrieval job. "
                "Size API/Celery/PG pool with Ollama parallel limits on staging."
            ),
        },
        "notes": [
            "Parse uses the bounded parser thread pool; embed uses deterministic vectors.",
            "Celery broker ping is not on the request path (unit-covered).",
            "Ollama reachability is probed; live inference under load is optional.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--rounds", type=int, default=2)
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(
            _run(concurrency=max(1, args.concurrency), rounds=max(1, args.rounds))
        )
    except InfrastructureError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_class": "infrastructure",
                    "error": str(exc),
                    "hint": "Run via make phase5-concurrency-smoke",
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
    return EXIT_OK if report.get("ok") else EXIT_APP


if __name__ == "__main__":
    raise SystemExit(main())
