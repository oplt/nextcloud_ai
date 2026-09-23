"""Phase 5: offline helpers for ANN recall math (no DB required)."""

from __future__ import annotations

from backend.evals.phase5_ann_benchmark import _recall_at_k, _recommend, _unit_vector


def test_unit_vector_is_normalized() -> None:
    vector = _unit_vector(7, 32)
    norm = sum(value * value for value in vector) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_recall_at_k_counts_intersection() -> None:
    expected = ["a", "b", "c"]
    assert _recall_at_k(expected, ["a", "x", "b"], 3) == 2 / 3
    assert _recall_at_k(expected, ["z"], 3) == 0.0


def test_recommend_prefers_fast_ann_within_recall_band() -> None:
    results = [
        {
            "mode": "exact",
            "authorized_recall_at_k": 1.0,
            "latency_seconds": {"p95": 0.02},
            "probes": None,
            "ef_search": None,
        },
        {
            "mode": "ivfflat",
            "authorized_recall_at_k": 0.99,
            "latency_seconds": {"p95": 0.01},
            "probes": 10,
            "ef_search": None,
        },
        {
            "mode": "hnsw",
            "authorized_recall_at_k": 1.0,
            "latency_seconds": {"p95": 0.005},
            "probes": None,
            "ef_search": 40,
        },
    ]
    pick = _recommend(results)
    assert pick["strategy"] == "hnsw"
    assert pick["ef_search"] == 40
