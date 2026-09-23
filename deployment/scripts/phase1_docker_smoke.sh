#!/usr/bin/env bash
# Phase 1A: build backend image + smoke migrate/API/worker/scheduler/seed/ready.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

COMPOSE="${DOCKER_COMPOSE:-docker compose}"
PROJECT="${PHASE1_COMPOSE_PROJECT:-phase1smoke}"
BUILD_RERANK="${PHASE1_BUILD_RERANK:-0}"
WAIT_SEC="${PHASE1_WAIT_SEC:-180}"
BACKEND_PORT="${PHASE1_BACKEND_PORT:-18000}"
BACKEND_HEALTH_URL="${BACKEND_HEALTH_URL:-http://localhost:${BACKEND_PORT}/api/v1/health/live}"
BACKEND_READY_URL="${BACKEND_READY_URL:-http://localhost:${BACKEND_PORT}/api/v1/health/ready}"
COMPOSE_FILE="$ROOT_DIR/.phase1-compose.generated.yml"
chmod +x deployment/scripts/phase1_compose_file.sh
bash deployment/scripts/phase1_compose_file.sh "$COMPOSE_FILE"
COMPOSE_CMD=($COMPOSE -p "$PROJECT" -f "$COMPOSE_FILE")

cleanup() {
  if [[ "${PHASE1_KEEP_STACK:-0}" == "1" ]]; then
    echo "PHASE1_KEEP_STACK=1 — leaving compose project ${PROJECT}"
    echo "compose file: ${COMPOSE_FILE}"
    return
  fi
  "${COMPOSE_CMD[@]}" down --remove-orphans >/dev/null 2>&1 || true
  rm -f "$COMPOSE_FILE"
}
trap cleanup EXIT

echo "==> Building backend image (BUILD_RERANK_MODEL=${BUILD_RERANK})"
"${COMPOSE_CMD[@]}" build \
  --build-arg "BUILD_RERANK_MODEL=${BUILD_RERANK}" \
  backend worker scheduler migrate

echo "==> Starting postgres redis ollama migrate"
"${COMPOSE_CMD[@]}" up -d postgres redis ollama
"${COMPOSE_CMD[@]}" up migrate

echo "==> Starting backend worker scheduler"
"${COMPOSE_CMD[@]}" up -d backend worker scheduler

echo "==> Waiting for live health at ${BACKEND_HEALTH_URL} (${WAIT_SEC}s)"
ready=0
for _ in $(seq 1 "$WAIT_SEC"); do
  if curl -fsS -o /dev/null "$BACKEND_HEALTH_URL" 2>/dev/null; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != "1" ]]; then
  echo "Backend live health timed out" >&2
  "${COMPOSE_CMD[@]}" ps >&2 || true
  "${COMPOSE_CMD[@]}" logs --tail=120 backend migrate >&2 || true
  exit 1
fi
echo "Backend live OK"

echo "==> Checking ready payload (db/redis/broker/rerank; ollama models optional for smoke)"
# Do not use curl -f: /ready returns 503 JSON when AI models are missing.
ready_json="$(curl -sS "$BACKEND_READY_URL" || true)"
READY_JSON="$ready_json" python3 - <<'PY'
import json, os
raw = os.environ.get("READY_JSON", "").strip()
if not raw:
    raise SystemExit("empty ready response")
payload = json.loads(raw)
rerank = payload.get("rerank") or {}
print(json.dumps({
    "status": payload.get("status"),
    "database": payload.get("database"),
    "redis": payload.get("redis"),
    "broker": payload.get("broker"),
    "rerank": rerank,
    "ai_runtime": payload.get("ai_runtime"),
}, indent=2, sort_keys=True))
if payload.get("database") != "ok":
    raise SystemExit("database not ok")
if payload.get("redis") != "ok":
    raise SystemExit("redis not ok")
if payload.get("broker") != "ok":
    raise SystemExit("broker not ok")
if rerank.get("enabled") and not rerank.get("ready") and not rerank.get("using_fallback"):
    raise SystemExit("rerank enabled but neither ready nor explicit fallback")
PY

echo "==> Verifying seed-admin module inside backend container"
"${COMPOSE_CMD[@]}" exec -T backend python -m backend.scripts.seed_admin

echo "==> Verifying celery app import on worker"
"${COMPOSE_CMD[@]}" exec -T worker \
  python -c "from backend.workers.celery_app import celery_app; print(celery_app.main)"

echo "==> Verifying beat scheduler process"
"${COMPOSE_CMD[@]}" exec -T scheduler \
  python -c "from backend.workers.celery_app import celery_app; print('beat-ok', celery_app.main)"

echo "==> Phase 1A docker smoke OK"
