from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class OfflineEvalRow:
    question: str
    expected_document_ids: list[str]
    retrieved_document_ids: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


def precision_at_k(expected: list[str], retrieved: list[str], k: int) -> float:
    if not expected or not retrieved:
        return 0.0
    head = retrieved[:k]
    exp = {str(x) for x in expected}
    hits = sum(1 for rid in head if str(rid) in exp)
    return hits / min(k, len(head)) if head else 0.0


def retrieval_hit_rate(expected: list[str], retrieved: list[str], k: int) -> float:
    if not expected:
        return 0.0
    head = {str(item) for item in retrieved[:k]}
    return 1.0 if any(str(item) in head for item in expected) else 0.0


def answer_correctness(expected_terms: list[str], answer: str) -> float:
    terms = [term.lower() for term in expected_terms if term]
    if not terms:
        return 0.0
    lowered = answer.lower()
    hits = sum(1 for term in terms if term in lowered)
    return hits / len(terms)


def citation_correctness(expected: list[str], cited: list[str]) -> float:
    if not expected or not cited:
        return 0.0
    expected_set = {str(item) for item in expected}
    cited_set = {str(item) for item in cited}
    return len(expected_set & cited_set) / len(cited_set)


def load_gold_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def append_metrics_log(path: Path | None, record: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
