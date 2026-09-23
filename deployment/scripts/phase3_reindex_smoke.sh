#!/usr/bin/env bash
# Phase 3: staged reindex promote/rollback on disposable Postgres.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

KEEP_INFRA="${PHASE3_KEEP_INFRA:-0}"
chmod +x deployment/scripts/phase2_infra.sh

# Reuse phase2 disposable PG/Redis ports to avoid collisions.
export PHASE2_PG_NAME="${PHASE3_PG_NAME:-phase3-pg}"
export PHASE2_REDIS_NAME="${PHASE3_REDIS_NAME:-phase3-redis}"
export PHASE2_PG_PORT="${PHASE3_PG_PORT:-15433}"
export PHASE2_REDIS_PORT="${PHASE3_REDIS_PORT:-16381}"

mapfile -t URLS < <(bash deployment/scripts/phase2_infra.sh up)
DATABASE_URL="${URLS[0]}"
REDIS_URL="${URLS[1]}"

cleanup() {
  if [[ "$KEEP_INFRA" == "1" ]]; then
    echo "PHASE3_KEEP_INFRA=1 — leaving phase3 infra up"
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
export JWT_SECRET_KEY=phase3-test-jwt-secret-not-for-prod
export SETTINGS_VAULT_KEY=phase3-test-vault-secret-not-for-prod
export NEXTCLOUD_BRIDGE_SHARED_SECRET=phase3-test-bridge-secret-not-for-prod
export PYTHONPATH="$ROOT_DIR"

echo "==> Migrate disposable DB"
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head

echo "==> Staged reindex promote/rollback"
backend/.venv/bin/python -m backend.scripts.phase3_reindex_smoke

echo "==> Phase 3 reindex smoke OK"
