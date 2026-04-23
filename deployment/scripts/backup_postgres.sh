#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deployment/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/deployment/backups}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
TARGET_FILE="${1:-$BACKUP_DIR/postgres-${TIMESTAMP}.sql.gz}"

mkdir -p "$BACKUP_DIR"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T postgres \
  sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' \
  | gzip -9 > "$TARGET_FILE"

echo "Wrote backup to $TARGET_FILE"
