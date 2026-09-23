#!/usr/bin/env bash
# Phase 4: held-out hard-negative threshold calibration (no DB).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

export PYTHONPATH="$ROOT_DIR"
export APP_ENV=test
export RAG_TRUE_RERANK_ENABLED=false

echo "==> Calibrate grounded floors on held-out positives/hard-negatives"
backend/.venv/bin/python -m backend.evals.phase4_threshold_calibrate

echo "==> Phase 4 threshold calibration OK"
