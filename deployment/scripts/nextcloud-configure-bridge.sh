#!/bin/bash
# Nextcloud before-starting hook.
# 1. Copies nc_ai_bridge from read-only seed dir into custom_apps (fresh each boot).
# 2. Enables the app and syncs config from env. Idempotent.
set -euo pipefail

cd /var/www/html

SEED_DIR="/nc_ai_bridge_seed"
TARGET_DIR="/var/www/html/custom_apps/nc_ai_bridge"

if [ -d "${SEED_DIR}" ]; then
    echo "[nc_ai_bridge hook] Syncing app from ${SEED_DIR} -> ${TARGET_DIR}"
    mkdir -p /var/www/html/custom_apps
    rm -rf "${TARGET_DIR}"
    cp -r "${SEED_DIR}" "${TARGET_DIR}"
else
    echo "[nc_ai_bridge hook] Seed dir ${SEED_DIR} missing, skipping copy."
fi

if ! php occ status 2>/dev/null | grep -q "installed: true"; then
    echo "[nc_ai_bridge hook] Nextcloud not installed yet, skipping app:enable."
    exit 0
fi

echo "[nc_ai_bridge hook] Enabling nc_ai_bridge app..."
php occ app:enable nc_ai_bridge || true

# Must be the FastAPI origin (port 8000 by default), not the Vite dev server — the
# browser POSTs bridge SSO to ${FASTAPI_BASE_URL}/api/v1/auth/nextcloud/sso/consume.
FASTAPI_BASE_URL="${NC_AI_BRIDGE_FASTAPI_BASE_URL:-http://localhost:5173}"
BRIDGE_SHARED_SECRET="${NEXTCLOUD_BRIDGE_SHARED_SECRET:-}"
BRIDGE_ISSUER="${NEXTCLOUD_BRIDGE_ISSUER:-nextcloud-bridge}"
BRIDGE_AUDIENCE="${NEXTCLOUD_BRIDGE_AUDIENCE:-fastapi-nextcloud}"
BRIDGE_TTL_SECONDS="${NEXTCLOUD_BRIDGE_TTL_SECONDS:-60}"
OVERWRITE_HOST="${OVERWRITEHOST:-}"
OVERWRITE_PROTOCOL="${OVERWRITEPROTOCOL:-}"
OVERWRITE_CLI_URL="${OVERWRITECLIURL:-}"
OVERWRITE_WEBROOT="${NEXTCLOUD_OVERWRITE_WEBROOT:-}"

if [ -z "${BRIDGE_SHARED_SECRET}" ]; then
    echo "[nc_ai_bridge hook] WARNING: NEXTCLOUD_BRIDGE_SHARED_SECRET is empty."
fi

if [ -n "${OVERWRITE_HOST}" ]; then
    php occ config:system:set overwritehost --value="${OVERWRITE_HOST}"
fi

if [ -n "${OVERWRITE_PROTOCOL}" ]; then
    php occ config:system:set overwriteprotocol --value="${OVERWRITE_PROTOCOL}"
fi

if [ -n "${OVERWRITE_CLI_URL}" ]; then
    php occ config:system:set overwrite.cli.url --value="${OVERWRITE_CLI_URL}"
fi

if [ -n "${OVERWRITE_WEBROOT}" ]; then
    php occ config:system:set overwritewebroot --value="${OVERWRITE_WEBROOT}"
    php occ config:system:set htaccess.RewriteBase --value="${OVERWRITE_WEBROOT}"
    php occ maintenance:update:htaccess
fi

php occ config:app:set nc_ai_bridge fastapi_base_url     --value="${FASTAPI_BASE_URL}"
php occ config:app:set nc_ai_bridge bridge_shared_secret --value="${BRIDGE_SHARED_SECRET}"
php occ config:app:set nc_ai_bridge bridge_issuer        --value="${BRIDGE_ISSUER}"
php occ config:app:set nc_ai_bridge bridge_audience      --value="${BRIDGE_AUDIENCE}"
php occ config:app:set nc_ai_bridge bridge_ttl_seconds   --value="${BRIDGE_TTL_SECONDS}"

echo "[nc_ai_bridge hook] Configured. fastapi_base_url=${FASTAPI_BASE_URL}"
