"""Unit tests for offline RAG metrics."""

from __future__ import annotations

from backend.evals.offline_scorer import (
    abstention_score,
    answer_correctness,
    answer_exclusion_ok,
    citation_support,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    precision_over_returned,
    recall_at_k,
    retrieval_hit_rate,
    score_retrieval,
)


def test_precision_at_k_uses_fixed_denominator() -> None:
    # Only 1 returned but k=3 → 1/3, not 1/1.
    assert precision_at_k(["a"], ["a"], 3) == 1.0 / 3.0


def test_precision_over_returned_is_separate() -> None:
    assert precision_over_returned(["a"], ["a"], k=3) == 1.0
    assert precision_at_k(["a"], ["a"], 3) != precision_over_returned(["a"], ["a"], k=3)


def test_document_unit_dedupes_repeated_ids() -> None:
    retrieved = ["a", "a", "b"]
    assert precision_at_k(["a", "b"], retrieved, 2, unit="document") == 1.0
    # Chunk unit keeps duplicate "a" slots; gold "b" never enters top-2.
    assert precision_at_k(["b"], retrieved, 2, unit="chunk") == 0.0
    # Document unit collapses to [a, b] so top-2 includes b → 1/2.
    assert precision_at_k(["b"], retrieved, 2, unit="document") == 0.5


def test_recall_mrr_ndcg() -> None:
    expected = ["gold"]
    retrieved = ["x", "gold", "y"]
    assert recall_at_k(expected, retrieved, 1) == 0.0
    assert recall_at_k(expected, retrieved, 2) == 1.0
    assert mean_reciprocal_rank(expected, retrieved) == 0.5
    assert ndcg_at_k(expected, retrieved, 2) > 0.0
    assert retrieval_hit_rate(expected, retrieved, 2) == 1.0


def test_answer_and_citation_and_abstention() -> None:
    assert (
        answer_correctness(["carry-over", "2024"], "Carry-over in 2024 is 5 days")
        == 1.0
    )
    assert answer_exclusion_ok(["noon"], "Total is 200") == 1.0
    assert answer_exclusion_ok(["noon"], "Lunch at noon") == 0.0
    assert citation_support(["a"], ["a", "b"]) == 0.5
    assert (
        abstention_score(
            should_abstain=True,
            answer="I could not verify this from the retrieved indexed sources.",
            retrieved_count=0,
        )
        == 1.0
    )
    assert (
        abstention_score(
            should_abstain=False,
            answer="The total is 200 EUR.",
            retrieved_count=2,
        )
        == 1.0
    )


def test_score_retrieval_bundle_keys() -> None:
    metrics = score_retrieval(
        expected_ids=["a"], retrieved_ids=["b", "a"], k_values=(3, 6)
    )
    assert "recall@3" in metrics
    assert "precision@6" in metrics
    assert "mrr" in metrics
    assert "ndcg@3" in metrics
    assert "precision_over_returned@6" in metrics
