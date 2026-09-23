#!/usr/bin/env bash
# Phase 4: fixture baseline vs disposable-PG final quality metrics.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

KEEP_INFRA="${PHASE4_KEEP_INFRA:-0}"
chmod +x deployment/scripts/phase2_infra.sh

export PHASE2_PG_NAME="${PHASE4_PG_NAME:-phase4-pg}"
export PHASE2_REDIS_NAME="${PHASE4_REDIS_NAME:-phase4-redis}"
export PHASE2_PG_PORT="${PHASE4_PG_PORT:-15434}"
export PHASE2_REDIS_PORT="${PHASE4_REDIS_PORT:-16382}"

mapfile -t URLS < <(bash deployment/scripts/phase2_infra.sh up)
DATABASE_URL="${URLS[0]}"
REDIS_URL="${URLS[1]}"

cleanup() {
  if [[ "$KEEP_INFRA" == "1" ]]; then
    echo "PHASE4_KEEP_INFRA=1 — leaving phase4 infra up"
    return
  fi
  bash deployment/scripts/phase2_infra.sh down >/dev/null
}
trap cleanup EXIT

export DATABASE_URL REDIS_URL
export CELERY_BROKER_URL="$REDIS_URL"
export CELERY_RESULT_BACKEND="$REDIS_URL"
export APP_ENV=test
export RAG_TRUE_RERANK_ENABLED=false
export EMBEDDING_PROVIDER=deterministic
export LLM_PROVIDER=stub
export JWT_SECRET_KEY=phase4-test-jwt-secret-not-for-prod
export SETTINGS_VAULT_KEY=phase4-test-vault-secret-not-for-prod
export NEXTCLOUD_BRIDGE_SHARED_SECRET=phase4-test-bridge-secret-not-for-prod
export PYTHONPATH="$ROOT_DIR"

echo "==> Migrate disposable DB"
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head

echo "==> Baseline (fixture) vs final (DB retrieval + verified extractive)"
backend/.venv/bin/python -m backend.evals.phase4_quality_compare

echo "==> Phase 4 quality compare OK"
