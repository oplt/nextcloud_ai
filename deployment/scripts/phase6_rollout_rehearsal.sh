#!/usr/bin/env bash
# Phase 6: staged rollout checklist rehearsal (local / disposable).
# Covers offline preflight, fresh migrate, fixture eval, reindex smoke,
# observability contract presence, and rollback notes. External SSO/IMAP
# remain operator-led when infrastructure is unavailable.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

KEEP_INFRA="${PHASE6_KEEP_INFRA:-0}"
REPORT_DIR="${PHASE6_REPORT_DIR:-/tmp/phase6-rollout-$$}"
mkdir -p "$REPORT_DIR"

chmod +x deployment/scripts/phase2_infra.sh
export PHASE2_PG_NAME="${PHASE6_PG_NAME:-phase6-pg}"
export PHASE2_REDIS_NAME="${PHASE6_REDIS_NAME:-phase6-redis}"
export PHASE2_PG_PORT="${PHASE6_PG_PORT:-15438}"
export PHASE2_REDIS_PORT="${PHASE6_REDIS_PORT:-16386}"

mapfile -t URLS < <(bash deployment/scripts/phase2_infra.sh up)
DATABASE_URL="${URLS[0]}"
REDIS_URL="${URLS[1]}"

cleanup() {
  if [[ "$KEEP_INFRA" == "1" ]]; then
    echo "PHASE6_KEEP_INFRA=1 — leaving phase6 infra up"
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
export JWT_SECRET_KEY=phase6-test-jwt-secret-not-for-prod
export SETTINGS_VAULT_KEY=phase6-test-vault-secret-not-for-prod
export NEXTCLOUD_BRIDGE_SHARED_SECRET=phase6-test-bridge-secret-not-for-prod
export PYTHONPATH="$ROOT_DIR"

echo "==> 1) Offline rollout preflight"
backend/.venv/bin/python -m backend.scripts.rollout_preflight \
  | tee "$REPORT_DIR/preflight.json"

echo "==> 2) Compat / queue drain inventory"
backend/.venv/bin/python -m backend.scripts.phase6_compat_inventory \
  | tee "$REPORT_DIR/compat_inventory.json"

echo "==> 3) Fresh migrate to head (backup stand-in = disposable empty DB)"
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head \
  | tee "$REPORT_DIR/migrate.log"
backend/.venv/bin/alembic -c backend/alembic.ini current \
  | tee "$REPORT_DIR/alembic_current.txt"

echo "==> 4) Offline evals (fixture + structure)"
make eval-fixture | tee "$REPORT_DIR/eval_fixture.json"
make eval-structure | tee "$REPORT_DIR/eval_structure.json"

echo "==> 5) Staged reindex promote/rollback rehearsal"
backend/.venv/bin/python -m backend.scripts.phase3_reindex_smoke \
  | tee "$REPORT_DIR/reindex_smoke.json"

echo "==> 6) Observability contract files present"
test -f deployment/prometheus/rules_rag.yml
test -f deployment/grafana/RAG_DASHBOARD.md
echo "prometheus_rules=ok grafana_docs=ok" | tee "$REPORT_DIR/observability.txt"

echo "==> 7) Rollback rehearsal notes (additive migrations; prior gen retained)"
cat > "$REPORT_DIR/rollback_notes.txt" <<'EOF'
Rollback rehearsal (local):
- Application: redeploy previous image; leave previous published index generation active.
- Database: migrations are additive; do not drop/rebuild vector or lexical indexes on app rollback.
- Downgrade only against a restored backup after explicit testing.
- Reindex smoke above already proved promote → rollback restores prior generation content.
External SSO/webhook/IMAP/ACL revocation remain operator-led on staging.
EOF
cat "$REPORT_DIR/rollback_notes.txt"

echo "==> Phase 6 rollout rehearsal OK (artifacts under $REPORT_DIR)"
echo "$REPORT_DIR" > "$REPORT_DIR/LOCATION.txt"
