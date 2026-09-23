#!/usr/bin/env bash
# Phase 5: concurrent retrieval/parse/embed/cache smoke on disposable Postgres.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

KEEP_INFRA="${PHASE5_KEEP_INFRA:-0}"
chmod +x deployment/scripts/phase2_infra.sh

export PHASE2_PG_NAME="${PHASE5_CONC_PG_NAME:-phase5-conc-pg}"
export PHASE2_REDIS_NAME="${PHASE5_CONC_REDIS_NAME:-phase5-conc-redis}"
export PHASE2_PG_PORT="${PHASE5_CONC_PG_PORT:-15437}"
export PHASE2_REDIS_PORT="${PHASE5_CONC_REDIS_PORT:-16385}"

mapfile -t URLS < <(bash deployment/scripts/phase2_infra.sh up)
DATABASE_URL="${URLS[0]}"
REDIS_URL="${URLS[1]}"

cleanup() {
  if [[ "$KEEP_INFRA" == "1" ]]; then
    echo "PHASE5_KEEP_INFRA=1 — leaving phase5-conc infra up"
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

CONCURRENCY="${PHASE5_CONCURRENCY:-8}"
ROUNDS="${PHASE5_CONC_ROUNDS:-2}"
echo "==> Concurrency smoke (concurrency=${CONCURRENCY}, rounds=${ROUNDS})"
backend/.venv/bin/python -m backend.evals.phase5_concurrency_smoke \
  --concurrency "$CONCURRENCY" \
  --rounds "$ROUNDS"

echo "==> Phase 5 concurrency smoke OK"
