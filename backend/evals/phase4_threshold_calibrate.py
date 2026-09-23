"""Phase 4: calibrate grounded relevance floors on held-out hard negatives.

Sweeps absolute_min_score × relative_floor_factor, measures selection
precision/recall and abstention on labeled positives vs hard negatives, then
recommends floors that keep positives while abstaining on all-negative cases.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from backend.rag.stores import RetrievalCandidate
from backend.services.retrieval_service import RetrievalService

DEFAULT_DATASET = Path(__file__).with_name("fixtures") / "heldout_relevance.json"


def _chunk(
    *,
    content: str,
    file_name: str,
    file_path: str,
):
    document = SimpleNamespace(
        id=uuid4(),
        file_name=file_name,
        file_path=file_path,
        document_type="memo",
        business_domain="ops",
        is_deleted=False,
    )
    return SimpleNamespace(
        id=uuid4(),
        content=content,
        section_title="",
        heading_path="",
        page_number=1,
        document=document,
    )


def _candidates(raw: list[dict[str, Any]]) -> list[tuple[RetrievalCandidate, bool]]:
    out: list[tuple[RetrievalCandidate, bool]] = []
    for item in raw:
        chunk = _chunk(
            content=str(item["content"]),
            file_name=str(item["file_name"]),
            file_path=str(item["file_path"]),
        )
        candidate = RetrievalCandidate(
            chunk=chunk,  # type: ignore[arg-type]
            semantic_score=float(item.get("semantic_score") or 0.0),
            keyword_score=float(item.get("lexical_score") or 0.0),
            fused_score=float(
                item.get("fused_score") or item.get("rerank_score") or 0.0
            ),
            rerank_score=float(item["rerank_score"])
            if item.get("rerank_score") is not None
            else None,
        )
        out.append((candidate, bool(item.get("relevant"))))
    return out


def _evaluate_case(
    service: RetrievalService,
    case: dict[str, Any],
    *,
    absolute_min_score: float,
    relative_floor_factor: float,
) -> dict[str, Any]:
    labeled = _candidates(list(case["candidates"]))
    ranked = [item for item, _ in labeled]
    # Sort like the final ranker: score desc.
    ranked = sorted(ranked, key=lambda item: item.score, reverse=True)
    selected = service._select_grounded_chunks(
        ranked_chunks=ranked,
        keyword_terms=list(case.get("keyword_terms") or []),
        top_k=3,
        absolute_min_score=absolute_min_score,
        relative_floor_factor=relative_floor_factor,
    )
    selected_ids = {str(chunk.id) for chunk, _ in selected}
    relevant_ids = {
        str(candidate.chunk.id) for candidate, relevant in labeled if relevant
    }
    true_pos = len(selected_ids & relevant_ids)
    false_pos = len(selected_ids - relevant_ids)
    false_neg = len(relevant_ids - selected_ids)
    abstained = len(selected) == 0
    expect_abstain = case.get("label") == "hard_negative" and not relevant_ids
    return {
        "id": case["id"],
        "label": case.get("label"),
        "selected": len(selected),
        "true_pos": true_pos,
        "false_pos": false_pos,
        "false_neg": false_neg,
        "abstained": abstained,
        "abstention_ok": (abstained == expect_abstain)
        if expect_abstain or abstained
        else True,
        "expect_abstain": expect_abstain,
    }


def _aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, float]:
    tp = sum(int(row["true_pos"]) for row in rows)
    fp = sum(int(row["false_pos"]) for row in rows)
    fn = sum(int(row["false_neg"]) for row in rows)
    hard_negs = [row for row in rows if row.get("expect_abstain")]
    abstain_ok = (
        sum(1 for row in hard_negs if row["abstained"]) / len(hard_negs)
        if hard_negs
        else 1.0
    )
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "hard_negative_abstention": abstain_ok,
        "false_positives": float(fp),
        "true_positives": float(tp),
    }


def calibrate(dataset: dict[str, Any]) -> dict[str, Any]:
    service = RetrievalService.__new__(RetrievalService)
    absolute_grid = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
    relative_grid = [0.50, 0.60, 0.72, 0.80, 0.90]
    sweeps: list[dict[str, Any]] = []
    for absolute in absolute_grid:
        for relative in relative_grid:
            rows = [
                _evaluate_case(
                    service,
                    case,
                    absolute_min_score=absolute,
                    relative_floor_factor=relative,
                )
                for case in dataset["cases"]
            ]
            metrics = _aggregate_rows(rows)
            sweeps.append(
                {
                    "absolute_min_score": absolute,
                    "relative_floor_factor": relative,
                    **metrics,
                }
            )

    # Prefer perfect hard-neg abstention + full positive recall, then max F1.
    # When tied, prefer the configured defaults if they are eligible; else
    # prefer stricter floors (higher absolute, then higher relative).
    eligible = [
        row
        for row in sweeps
        if row["hard_negative_abstention"] >= 0.999 and row["recall"] >= 0.999
    ]
    defaults = dataset.get("defaults") or {}
    default_abs = float(defaults.get("absolute_min_score", 0.35))
    default_rel = float(defaults.get("relative_floor_factor", 0.72))
    configured_match = [
        row
        for row in eligible
        if abs(row["absolute_min_score"] - default_abs) < 1e-9
        and abs(row["relative_floor_factor"] - default_rel) < 1e-9
    ]
    if configured_match:
        recommended = configured_match[0]
    else:
        pool = eligible or sweeps
        recommended = max(
            pool,
            key=lambda row: (
                row["hard_negative_abstention"],
                row["f1"],
                row["precision"],
                row["absolute_min_score"],
                row["relative_floor_factor"],
            ),
        )
    return {
        "ok": True,
        "case_count": len(dataset["cases"]),
        "recommended": recommended,
        "configured_defaults": defaults,
        "matches_configured": (
            abs(
                float(defaults.get("absolute_min_score", -1))
                - recommended["absolute_min_score"]
            )
            < 1e-9
            and abs(
                float(defaults.get("relative_floor_factor", -1))
                - recommended["relative_floor_factor"]
            )
            < 1e-9
        ),
        "sweep_top": sorted(
            sweeps,
            key=lambda row: (
                row["hard_negative_abstention"],
                row["f1"],
                row["precision"],
                row["absolute_min_score"],
                row["relative_floor_factor"],
            ),
            reverse=True,
        )[:8],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args(argv)
    try:
        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        report = calibrate(dataset)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    # Fail closed if hard negatives would not abstain at the recommended floor.
    if report["recommended"]["hard_negative_abstention"] < 0.999:
        return 1
    if report["recommended"]["recall"] < 0.999:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
