#!/usr/bin/env bash
# Phase 5: DB-backed retrieval workload benchmark on disposable Postgres.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

KEEP_INFRA="${PHASE5_KEEP_INFRA:-0}"
chmod +x deployment/scripts/phase2_infra.sh

export PHASE2_PG_NAME="${PHASE5_PG_NAME:-phase5-pg}"
export PHASE2_REDIS_NAME="${PHASE5_REDIS_NAME:-phase5-redis}"
export PHASE2_PG_PORT="${PHASE5_PG_PORT:-15435}"
export PHASE2_REDIS_PORT="${PHASE5_REDIS_PORT:-16383}"

mapfile -t URLS < <(bash deployment/scripts/phase2_infra.sh up)
DATABASE_URL="${URLS[0]}"
REDIS_URL="${URLS[1]}"

cleanup() {
  if [[ "$KEEP_INFRA" == "1" ]]; then
    echo "PHASE5_KEEP_INFRA=1 — leaving phase5 infra up"
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
export JWT_SECRET_KEY=phase5-test-jwt-secret-not-for-prod
export SETTINGS_VAULT_KEY=phase5-test-vault-secret-not-for-prod
export NEXTCLOUD_BRIDGE_SHARED_SECRET=phase5-test-bridge-secret-not-for-prod
export PYTHONPATH="$ROOT_DIR"

echo "==> Migrate disposable DB"
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head

ITERATIONS="${PHASE5_DB_ITERS:-5}"
echo "==> DB workload benchmark (iterations=${ITERATIONS})"
backend/.venv/bin/python -m backend.evals.phase5_db_benchmark --iterations "$ITERATIONS"

echo "==> Phase 5 DB benchmark OK"
