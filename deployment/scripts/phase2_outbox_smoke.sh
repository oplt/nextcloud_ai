#!/usr/bin/env bash
# Phase 2: outbox/lease/generation smoke against disposable Postgres+Redis.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

KEEP_INFRA="${PHASE2_KEEP_INFRA:-0}"
chmod +x deployment/scripts/phase2_infra.sh

mapfile -t URLS < <(bash deployment/scripts/phase2_infra.sh up)
DATABASE_URL="${URLS[0]}"
REDIS_URL="${URLS[1]}"

cleanup() {
  if [[ "$KEEP_INFRA" == "1" ]]; then
    echo "PHASE2_KEEP_INFRA=1 — leaving phase2 infra up"
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
export JWT_SECRET_KEY=phase2-test-jwt-secret-not-for-prod
export SETTINGS_VAULT_KEY=phase2-test-vault-secret-not-for-prod
export NEXTCLOUD_BRIDGE_SHARED_SECRET=phase2-test-bridge-secret-not-for-prod
export PYTHONPATH="$ROOT_DIR"

echo "==> Migrate disposable DB to head"
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head

echo "==> Outbox / lease / generation integration"
backend/.venv/bin/python -m backend.scripts.phase2_outbox_smoke

echo "==> Phase 2 outbox smoke OK"
