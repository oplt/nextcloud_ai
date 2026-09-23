"""Offline RAG metric definitions.

Units
-----
* **chunk** rankings use chunk IDs (or chunk-stable keys).
* **document** rankings deduplicate by first occurrence of each document ID.

Precision@k always uses fixed denominator ``k``. Precision over the items
actually returned is exposed separately as ``precision_over_returned``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Unit = Literal["chunk", "document"]


@dataclass
class OfflineEvalRow:
    """Validated evaluation case contract (gold labels scoring-only)."""

    id: str
    question: str
    expected_document_ids: list[str] = field(default_factory=list)
    expected_chunk_ids: list[str] = field(default_factory=list)
    expected_answer_contains: list[str] = field(default_factory=list)
    expected_answer_excludes: list[str] = field(default_factory=list)
    expected_cited_document_ids: list[str] = field(default_factory=list)
    # Explicit request scope only — never derived from expected_* gold labels.
    request_document_ids: list[str] = field(default_factory=list)
    request_auth: str | None = None
    language: str | None = None
    unanswerable: bool = False
    should_abstain: bool = False
    tags: list[str] = field(default_factory=list)
    notes: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> OfflineEvalRow:
        return cls(
            id=str(raw.get("id") or raw.get("question") or "unknown"),
            question=str(raw["question"]),
            expected_document_ids=[
                str(x) for x in (raw.get("expected_document_ids") or [])
            ],
            expected_chunk_ids=[str(x) for x in (raw.get("expected_chunk_ids") or [])],
            expected_answer_contains=[
                str(x) for x in (raw.get("expected_answer_contains") or [])
            ],
            expected_answer_excludes=[
                str(x) for x in (raw.get("expected_answer_excludes") or [])
            ],
            expected_cited_document_ids=[
                str(x) for x in (raw.get("expected_cited_document_ids") or [])
            ],
            request_document_ids=[
                str(x) for x in (raw.get("request_document_ids") or [])
            ],
            request_auth=(
                str(raw["request_auth"])
                if raw.get("request_auth") is not None
                else None
            ),
            language=str(raw["language"]) if raw.get("language") is not None else None,
            unanswerable=bool(raw.get("unanswerable") or raw.get("should_abstain")),
            should_abstain=bool(raw.get("should_abstain") or raw.get("unanswerable")),
            tags=[str(x) for x in (raw.get("tags") or [])],
            notes=str(raw["notes"]) if raw.get("notes") is not None else None,
            metadata=dict(raw.get("metadata") or {}),
        )


def _as_str_list(values: list[Any]) -> list[str]:
    return [str(v) for v in values]


def dedupe_preserve_order(ids: list[Any]) -> list[str]:
    """First-occurrence document/chunk ID order (ranking position preserved)."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in ids:
        key = str(raw)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def normalize_ranking(ids: list[Any], *, unit: Unit) -> list[str]:
    """Normalize a ranked ID list for the chosen evaluation unit."""
    as_str = _as_str_list(ids)
    if unit == "document":
        return dedupe_preserve_order(as_str)
    return as_str


def precision_at_k(
    expected: list[str],
    retrieved: list[str],
    k: int,
    *,
    unit: Unit = "document",
) -> float:
    """Fixed-denominator Precision@k: hits in top-k / k."""
    if k <= 0:
        return 0.0
    exp = {str(x) for x in expected}
    if not exp:
        return 0.0
    head = normalize_ranking(retrieved, unit=unit)[:k]
    hits = sum(1 for rid in head if rid in exp)
    return hits / float(k)


def precision_over_returned(
    expected: list[str],
    retrieved: list[str],
    *,
    unit: Unit = "document",
    k: int | None = None,
) -> float:
    """Precision over items actually returned (not fixed-k). Named separately."""
    exp = {str(x) for x in expected}
    ranked = normalize_ranking(retrieved, unit=unit)
    if k is not None:
        ranked = ranked[:k]
    if not exp or not ranked:
        return 0.0
    hits = sum(1 for rid in ranked if rid in exp)
    return hits / float(len(ranked))


def recall_at_k(
    expected: list[str],
    retrieved: list[str],
    k: int,
    *,
    unit: Unit = "document",
) -> float:
    """Recall@k: |relevant ∩ top-k| / |relevant|."""
    exp = {str(x) for x in expected}
    if not exp or k <= 0:
        return 0.0
    head = set(normalize_ranking(retrieved, unit=unit)[:k])
    return len(exp & head) / float(len(exp))


def retrieval_hit_rate(
    expected: list[str],
    retrieved: list[str],
    k: int,
    *,
    unit: Unit = "document",
) -> float:
    """Binary any-hit@k (1 if at least one gold ID in top-k)."""
    return 1.0 if recall_at_k(expected, retrieved, k, unit=unit) > 0.0 else 0.0


def mean_reciprocal_rank(
    expected: list[str],
    retrieved: list[str],
    *,
    unit: Unit = "document",
) -> float:
    """MRR over the full retrieved ranking (first relevant rank)."""
    exp = {str(x) for x in expected}
    if not exp:
        return 0.0
    for index, rid in enumerate(normalize_ranking(retrieved, unit=unit), start=1):
        if rid in exp:
            return 1.0 / float(index)
    return 0.0


def _dcg(relevances: list[float]) -> float:
    total = 0.0
    for index, rel in enumerate(relevances, start=1):
        total += (2.0**rel - 1.0) / math.log2(index + 1.0)
    return total


def ndcg_at_k(
    expected: list[str],
    retrieved: list[str],
    k: int,
    *,
    unit: Unit = "document",
) -> float:
    """Binary-relevance nDCG@k."""
    if k <= 0:
        return 0.0
    exp = {str(x) for x in expected}
    if not exp:
        return 0.0
    head = normalize_ranking(retrieved, unit=unit)[:k]
    gains = [1.0 if rid in exp else 0.0 for rid in head]
    ideal_hits = min(len(exp), k)
    ideal = [1.0] * ideal_hits + [0.0] * (k - ideal_hits)
    ideal_dcg = _dcg(ideal)
    if ideal_dcg <= 0.0:
        return 0.0
    return _dcg(gains) / ideal_dcg


def answer_correctness(expected_terms: list[str], answer: str) -> float:
    """Fraction of required answer terms present (case-insensitive substring)."""
    terms = [term.lower() for term in expected_terms if term]
    if not terms:
        return 0.0
    lowered = answer.lower()
    hits = sum(1 for term in terms if term in lowered)
    return hits / float(len(terms))


def answer_exclusion_ok(forbidden_terms: list[str], answer: str) -> float:
    """1.0 if none of the forbidden terms appear in the answer."""
    terms = [term.lower() for term in forbidden_terms if term]
    if not terms:
        return 1.0
    lowered = answer.lower()
    return 0.0 if any(term in lowered for term in terms) else 1.0


_ABSTAIN_MARKERS = (
    "could not verify",
    "insufficient",
    "not enough",
    "do not have enough",
    "no relevant",
    "cannot answer",
    "can't answer",
    "unable to answer",
    "i don't know",
    "i do not know",
    "no grounded sources",
    "abstain",
)


def abstention_score(
    *,
    should_abstain: bool,
    answer: str,
    retrieved_count: int,
    cited_count: int | None = None,
) -> float:
    """Score abstention behavior for answerable vs unanswerable cases."""
    lowered = (answer or "").lower().strip()
    markers_hit = any(marker in lowered for marker in _ABSTAIN_MARKERS)
    cited = 0 if cited_count is None else cited_count
    empty_evidence = retrieved_count == 0 and cited == 0
    empty_answer = not lowered
    did_abstain = markers_hit or empty_evidence or empty_answer
    if should_abstain:
        return 1.0 if did_abstain else 0.0
    return 0.0 if did_abstain else 1.0


def citation_support(
    expected: list[str],
    cited: list[str],
    *,
    unit: Unit = "document",
) -> float:
    """Fraction of cited IDs that are gold-relevant (support precision)."""
    exp = {str(x) for x in expected}
    cited_ranked = normalize_ranking(cited, unit=unit)
    if not exp or not cited_ranked:
        return 0.0
    supported = sum(1 for cid in cited_ranked if cid in exp)
    return supported / float(len(cited_ranked))


def citation_correctness(expected: list[str], cited: list[str]) -> float:
    """Backward-compatible alias for document-unit citation_support."""
    return citation_support(expected, cited, unit="document")


def citation_recall(
    expected: list[str],
    cited: list[str],
    *,
    unit: Unit = "document",
) -> float:
    """Fraction of gold IDs that appear among citations."""
    exp = {str(x) for x in expected}
    if not exp:
        return 0.0
    cited_set = set(normalize_ranking(cited, unit=unit))
    return len(exp & cited_set) / float(len(exp))


def score_retrieval(
    *,
    expected_ids: list[str],
    retrieved_ids: list[str],
    k_values: tuple[int, ...] = (3, 6),
    unit: Unit = "document",
) -> dict[str, float]:
    """Bundle standard retrieval metrics for one ranking."""
    metrics: dict[str, float] = {
        "mrr": mean_reciprocal_rank(expected_ids, retrieved_ids, unit=unit),
    }
    for k in k_values:
        metrics[f"recall@{k}"] = recall_at_k(expected_ids, retrieved_ids, k, unit=unit)
        metrics[f"precision@{k}"] = precision_at_k(
            expected_ids, retrieved_ids, k, unit=unit
        )
        metrics[f"precision_over_returned@{k}"] = precision_over_returned(
            expected_ids, retrieved_ids, unit=unit, k=k
        )
        metrics[f"ndcg@{k}"] = ndcg_at_k(expected_ids, retrieved_ids, k, unit=unit)
        metrics[f"hit_rate@{k}"] = retrieval_hit_rate(
            expected_ids, retrieved_ids, k, unit=unit
        )
    return metrics


def load_gold_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def load_eval_rows(path: Path) -> list[OfflineEvalRow]:
    return [OfflineEvalRow.from_dict(raw) for raw in load_gold_rows(path)]


def append_metrics_log(path: Path | None, record: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def mean_metrics(records: list[dict[str, Any]], keys: list[str]) -> dict[str, float]:
    """Mean of numeric metric keys across records (skip missing/non-numeric)."""
    totals: dict[str, float] = {key: 0.0 for key in keys}
    counts: dict[str, int] = {key: 0 for key in keys}
    for record in records:
        for key in keys:
            value = record.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[key] += float(value)
                counts[key] += 1
    return {key: totals[key] / counts[key] for key in keys if counts[key] > 0}
