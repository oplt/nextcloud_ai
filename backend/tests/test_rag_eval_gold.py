from __future__ import annotations

from pathlib import Path

from backend.evals.offline_scorer import load_gold_rows, precision_at_k


def test_rag_gold_file_is_valid_jsonl() -> None:
    path = Path(__file__).resolve().parents[1] / "evals" / "rag_gold.jsonl"
    rows = load_gold_rows(path)
    assert len(rows) >= 1
    for row in rows:
        assert "question" in row
        assert isinstance(row["question"], str)


def test_precision_at_k() -> None:
    p = precision_at_k(["a", "b"], ["x", "a", "c"], 3)
    assert abs(p - (1 / 3)) < 0.0001
