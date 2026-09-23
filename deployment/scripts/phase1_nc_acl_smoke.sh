#!/usr/bin/env bash
# Phase 1B: exercise grant types against a live docker Nextcloud OCS API.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

COMPOSE="${DOCKER_COMPOSE:-docker compose}"
PROJECT="${PHASE1_COMPOSE_PROJECT:-phase1smoke}"
WAIT_SEC="${PHASE1_WAIT_SEC:-300}"
NEXTCLOUD_PORT="${PHASE1_NEXTCLOUD_PORT:-18081}"
NC_URL="${PHASE1_NEXTCLOUD_URL:-http://localhost:${NEXTCLOUD_PORT}}"
NC_HEALTH="${PHASE1_NEXTCLOUD_HEALTH_URL:-${NC_URL}/status.php}"
ADMIN_USER="${NEXTCLOUD_ADMIN_USER:-admin}"
ADMIN_PASS="${NEXTCLOUD_ADMIN_PASSWORD:-admin}"
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

echo "==> Starting Nextcloud for ACL grant smoke"
"${COMPOSE_CMD[@]}" up -d postgres redis ollama
"${COMPOSE_CMD[@]}" up migrate
"${COMPOSE_CMD[@]}" up -d backend worker scheduler frontend nextcloud-db nextcloud

echo "==> Waiting for Nextcloud"
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
  "${COMPOSE_CMD[@]}" logs --tail=80 nextcloud >&2 || true
  exit 1
fi

"${COMPOSE_CMD[@]}" exec -T -u www-data nextcloud \
  bash -lc 'export OC_PASS=peerpass12345; php occ user:add --password-from-env peer || php occ user:resetpassword --password-from-env peer'
"${COMPOSE_CMD[@]}" exec -T -u www-data nextcloud \
  php occ group:add finance || true
"${COMPOSE_CMD[@]}" exec -T -u www-data nextcloud \
  php occ group:adduser finance peer || true

# Confirm WebDAV root is reachable before creating fixtures.
dav_ok=0
for _ in $(seq 1 60); do
  code="$(curl -s -o /dev/null -w '%{http_code}' -u "${ADMIN_USER}:${ADMIN_PASS}" \
    "${NC_URL}/remote.php/dav/files/${ADMIN_USER}/")"
  if [[ "$code" == "207" || "$code" == "200" ]]; then
    dav_ok=1
    break
  fi
  sleep 2
done
if [[ "$dav_ok" != "1" ]]; then
  echo "WebDAV not ready for admin user" >&2
  exit 1
fi

FOLDER="phase1_acl_$$"
curl -fsS -u "${ADMIN_USER}:${ADMIN_PASS}" -X MKCOL \
  "${NC_URL}/remote.php/dav/files/${ADMIN_USER}/${FOLDER}" >/dev/null
echo "nested secret" | curl -fsS -u "${ADMIN_USER}:${ADMIN_PASS}" -X PUT \
  -T - "${NC_URL}/remote.php/dav/files/${ADMIN_USER}/${FOLDER}/nested.txt" >/dev/null

OCS="${NC_URL}/ocs/v2.php/apps/files_sharing/api/v1/shares"
AUTH=(-u "${ADMIN_USER}:${ADMIN_PASS}" -H "OCS-APIRequest: true" -H "Accept: application/json")

curl -fsS "${AUTH[@]}" -X POST "$OCS" \
  -d "path=/${FOLDER}" -d "shareType=0" -d "shareWith=peer" -d "permissions=1" \
  >/tmp/phase1-share-user.json

curl -fsS "${AUTH[@]}" -X POST "$OCS" \
  -d "path=/${FOLDER}" -d "shareType=1" -d "shareWith=finance" -d "permissions=1" \
  >/tmp/phase1-share-group.json

curl -fsS "${AUTH[@]}" -X POST "$OCS" \
  -d "path=/${FOLDER}/nested.txt" -d "shareType=3" -d "permissions=1" \
  >/tmp/phase1-share-public.json

curl -fsS "${AUTH[@]}" -X POST "$OCS" \
  -d "path=/${FOLDER}/nested.txt" -d "shareType=3" -d "permissions=1" \
  -d "password=SecretLink1!" \
  >/tmp/phase1-share-protected.json

YESTERDAY="$(date -u -d 'yesterday' +%Y-%m-%d 2>/dev/null || date -u -v-1d +%Y-%m-%d)"
curl -fsS "${AUTH[@]}" -X POST "$OCS" \
  -d "path=/${FOLDER}/nested.txt" -d "shareType=0" -d "shareWith=peer" \
  -d "permissions=1" -d "expireDate=${YESTERDAY}" \
  >/tmp/phase1-share-expired.json || true

export PHASE1_NC_BASE_URL="$NC_URL"
export PHASE1_NC_USER="$ADMIN_USER"
export PHASE1_NC_PASSWORD="$ADMIN_PASS"
export PHASE1_NC_PATH="/${FOLDER}/nested.txt"

PYTHONPATH="$ROOT_DIR" backend/.venv/bin/python - <<'PY'
import asyncio
import json
import os
from pydantic import SecretStr
from backend.connectors.nextcloud.client import AsyncNextcloudClient
from backend.connectors.nextcloud.config import NextcloudConnectorConfig
from backend.connectors.nextcloud.identity import namespace_nc_group, namespace_nc_user
from backend.connectors.nextcloud.permissions import (
    CIRCLE_SHARE,
    EMAIL_SHARE,
    FEDERATED_SHARE,
    TALK_CONVERSATION_SHARE,
    NextcloudPermissionService,
    SHARE_TYPE_SUPPORT,
)

async def main() -> None:
    base = os.environ["PHASE1_NC_BASE_URL"]
    path = os.environ["PHASE1_NC_PATH"]
    cfg = NextcloudConnectorConfig(
        base_url=base,
        username=os.environ["PHASE1_NC_USER"],
        app_password=SecretStr(os.environ["PHASE1_NC_PASSWORD"]),
    )
    client = AsyncNextcloudClient(cfg)
    try:
        service = NextcloudPermissionService(client)
        acl = await service.build_acl_for_path(path, owner_user_id="admin")
    finally:
        await client.aclose()
    peer = namespace_nc_user(base, "peer")
    finance = namespace_nc_group(base, "finance")
    assert peer in acl.allowed_user_ids, acl.allowed_user_ids
    assert finance in acl.allowed_group_ids, acl.allowed_group_ids
    assert acl.public_link_enabled is False
    assert acl.public_link_open_read_observed is True
    for share_type in (EMAIL_SHARE, FEDERATED_SHARE, CIRCLE_SHARE, TALK_CONVERSATION_SHARE):
        assert SHARE_TYPE_SUPPORT[share_type] == "unsupported_fail_closed"
    report = {
        "path": path,
        "allowed_user_ids": acl.allowed_user_ids,
        "allowed_group_ids": acl.allowed_group_ids,
        "public_link_enabled": acl.public_link_enabled,
        "public_link_open_read_observed": acl.public_link_open_read_observed,
        "unresolved_share_types": acl.unresolved_share_types,
        "public_link_notes": acl.public_link_notes,
        "share_type_support": {str(k): v for k, v in SHARE_TYPE_SUPPORT.items()},
        "inherited_parent_share_applied": peer in acl.allowed_user_ids,
    }
    print(json.dumps({"ok": True, **report}, indent=2, sort_keys=True))

asyncio.run(main())
PY

echo "==> Phase 1B Nextcloud grant smoke OK"
echo "Note: federated/circles/Talk not creatable on stock NC image → fail-closed unit coverage + matrix docs."
