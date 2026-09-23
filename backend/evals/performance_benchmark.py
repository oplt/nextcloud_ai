"""Reproducible offline latency/resource baseline for the seeded RAG workload."""

from __future__ import annotations

import argparse
import json
import resource
import time
import tracemalloc

from .fixture_loader import load_fixture_bundle
from .run_offline_eval import _aggregate, _percentile, run_fixture


def benchmark(*, iterations: int) -> dict[str, object]:
    bundle = load_fixture_bundle()
    iteration_seconds: list[float] = []
    all_records: list[dict[str, object]] = []
    tracemalloc.start()
    started = time.perf_counter()
    try:
        for _ in range(iterations):
            iteration_started = time.perf_counter()
            records = run_fixture(bundle, with_answer=False, top_k=6)
            iteration_seconds.append(time.perf_counter() - iteration_started)
            all_records.extend(records)
    finally:
        elapsed = time.perf_counter() - started
        _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    iteration_seconds.sort()
    aggregate = _aggregate(all_records)
    case_count = len(all_records)
    return {
        "mode": "fixture_retrieval",
        "iterations": iterations,
        "cases": case_count,
        "elapsed_seconds": elapsed,
        "throughput_cases_per_second": case_count / elapsed if elapsed else 0.0,
        "iteration_latency_seconds": {
            "p50": _percentile(iteration_seconds, 0.50),
            "p95": _percentile(iteration_seconds, 0.95),
            "p99": _percentile(iteration_seconds, 0.99),
        },
        "event_loop_lag_seconds": None,
        "python_peak_memory_bytes": peak_bytes,
        "process_max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "authorized_recall_at_6": aggregate["means"].get("recall@6", 0.0),
        "sql_statements": 0,
        "database_connections": 0,
        "model_loads": 0,
        "limitations": [
            "Offline fixture mode: PostgreSQL/pgvector, Redis, and model inference are not exercised.",
            "Event-loop lag is not applicable to this synchronous CLI fixture workload.",
            "For DB/model workload metrics use: make phase5-db-benchmark",
            "For ANN strategy comparison use: make phase5-ann-benchmark",
            "For concurrent capacity smoke use: make phase5-concurrency-smoke",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=25)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")
    report = benchmark(iterations=args.iterations)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
