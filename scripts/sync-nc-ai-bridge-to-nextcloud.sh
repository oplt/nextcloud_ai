#!/usr/bin/env bash
# Copy repo nc_ai_bridge into a running Nextcloud tree (local or VM).
# Docker-based Nextcloud: restart the container instead; the entrypoint hook copies from the seed mount.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NC_ROOT="${NEXTCLOUD_HTML_ROOT:?Set NEXTCLOUD_HTML_ROOT to your Nextcloud webroot (directory that contains custom_apps), e.g. /var/www/html}"

if [[ ! -d "${NC_ROOT}/custom_apps" ]]; then
  echo "error: ${NC_ROOT}/custom_apps not found — is NEXTCLOUD_HTML_ROOT correct?" >&2
  exit 1
fi

DEST="${NC_ROOT}/custom_apps/nc_ai_bridge"
rm -rf "${DEST}"
cp -a "${REPO_ROOT}/nc_ai_bridge" "${DEST}"
echo "Synced nc_ai_bridge -> ${DEST}"
echo "Reload app (as www-data or your NC user), e.g.:"
echo "  php occ app:disable nc_ai_bridge && php occ app:enable nc_ai_bridge"
