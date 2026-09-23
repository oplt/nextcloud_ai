#!/usr/bin/env bash
# Phase 1A/1B: install nc_ai_bridge on docker Nextcloud and verify routes/bootstrap.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

COMPOSE="${DOCKER_COMPOSE:-docker compose}"
PROJECT="${PHASE1_COMPOSE_PROJECT:-phase1smoke}"
WAIT_SEC="${PHASE1_WAIT_SEC:-300}"
BACKEND_PORT="${PHASE1_BACKEND_PORT:-18000}"
NEXTCLOUD_PORT="${PHASE1_NEXTCLOUD_PORT:-18081}"
NC_URL="${PHASE1_NEXTCLOUD_URL:-http://localhost:${NEXTCLOUD_PORT}}"
NC_HEALTH="${PHASE1_NEXTCLOUD_HEALTH_URL:-${NC_URL}/status.php}"
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

echo "==> Starting Nextcloud stack for bridge smoke"
"${COMPOSE_CMD[@]}" up -d postgres redis ollama
"${COMPOSE_CMD[@]}" up migrate
"${COMPOSE_CMD[@]}" up -d backend worker scheduler frontend nextcloud-db nextcloud

echo "==> Waiting for Nextcloud ${NC_HEALTH}"
ready=0
for _ in $(seq 1 "$WAIT_SEC"); do
  if curl -fsS -o /dev/null "$NC_HEALTH"; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != "1" ]]; then
  echo "Nextcloud health timed out" >&2
  "${COMPOSE_CMD[@]}" ps >&2 || true
  "${COMPOSE_CMD[@]}" logs --tail=100 nextcloud >&2 || true
  exit 1
fi

echo "==> Ensuring nc_ai_bridge enabled"
"${COMPOSE_CMD[@]}" exec -T -u www-data nextcloud \
  php occ app:enable nc_ai_bridge

echo "==> App list / routes"
"${COMPOSE_CMD[@]}" exec -T -u www-data nextcloud \
  php occ app:list | tee /tmp/phase1-bridge-apps.txt | grep -E 'nc_ai_bridge'

"${COMPOSE_CMD[@]}" exec -T -u www-data nextcloud \
  php occ config:app:get nc_ai_bridge fastapi_base_url || true
"${COMPOSE_CMD[@]}" exec -T -u www-data nextcloud \
  php occ config:app:get nc_ai_bridge bridge_shared_secret >/dev/null

"${COMPOSE_CMD[@]}" exec -T -u www-data nextcloud \
  php occ route:list 2>/dev/null | tee /tmp/phase1-bridge-routes.txt | \
  grep -E 'nc_ai_bridge\.(page\.index|auth\.bootstrap)'

PAGE_CODE="$(curl -s -o /dev/null -w '%{http_code}' "${NC_URL}/apps/nc_ai_bridge/")"
if [[ "$PAGE_CODE" == "404" ]]; then
  echo "bridge page route returned 404" >&2
  exit 1
fi
echo "bridge page HTTP ${PAGE_CODE} (not 404)"

BOOT_CODE="$(curl -s -o /tmp/phase1-bootstrap.json -w '%{http_code}' \
  -X POST "${NC_URL}/apps/nc_ai_bridge/bootstrap")"
if [[ "$BOOT_CODE" != "401" && "$BOOT_CODE" != "303" && "$BOOT_CODE" != "302" ]]; then
  echo "unexpected bootstrap status ${BOOT_CODE}" >&2
  cat /tmp/phase1-bootstrap.json >&2 || true
  exit 1
fi
echo "anonymous bootstrap HTTP ${BOOT_CODE} (auth required)"

echo "==> CSRF / logout contracts"
grep -q 'NoCSRFRequired' nc_ai_bridge/lib/Controller/AuthController.php && {
  echo "AuthController must NOT use NoCSRFRequired" >&2
  exit 1
}
grep -q 'NoAdminRequired' nc_ai_bridge/lib/Controller/AuthController.php
grep -q 'Unauthenticated' nc_ai_bridge/lib/Controller/AuthController.php
grep -q "'jti'" nc_ai_bridge/lib/Controller/AuthController.php
grep -q 'encodeJwt' nc_ai_bridge/lib/Controller/AuthController.php

echo "==> Phase 1 bridge smoke OK (backend host port ${BACKEND_PORT})"
