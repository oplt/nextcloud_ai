#!/usr/bin/env bash
# Exit 0 when Nextcloud status.php returns HTTP 200, else 1 after MAX tries (1s apart).
set -euo pipefail
URL="${1:?health url}"
MAX="${2:-25}"
for _ in $(seq 1 "$MAX"); do
  code="$(curl -s -o /dev/null -w "%{http_code}" "$URL" 2>/dev/null || true)"
  if [ "$code" = "200" ]; then
    exit 0
  fi
  sleep 1
done
exit 1
