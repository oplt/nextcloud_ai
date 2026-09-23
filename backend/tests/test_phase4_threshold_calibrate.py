"""Phase 4: held-out threshold calibration selects configured floors."""

from __future__ import annotations

import json
from pathlib import Path

from backend.evals.phase4_threshold_calibrate import calibrate

_DATASET = (
    Path(__file__).resolve().parents[1]
    / "evals"
    / "fixtures"
    / "heldout_relevance.json"
)


def test_heldout_calibration_recommends_configured_floors() -> None:
    dataset = json.loads(_DATASET.read_text(encoding="utf-8"))
    report = calibrate(dataset)
    assert report["ok"] is True
    assert report["matches_configured"] is True
    assert report["recommended"]["hard_negative_abstention"] == 1.0
    assert report["recommended"]["recall"] == 1.0
    assert report["recommended"]["precision"] == 1.0
    assert report["recommended"]["absolute_min_score"] == 0.35
    assert report["recommended"]["relative_floor_factor"] == 0.72
