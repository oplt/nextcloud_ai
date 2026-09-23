#!/usr/bin/env bash
# Phase 2: disposable Postgres + Redis for outbox/lease/migrate smokes.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PG_NAME="${PHASE2_PG_NAME:-phase2-pg}"
REDIS_NAME="${PHASE2_REDIS_NAME:-phase2-redis}"
PG_PORT="${PHASE2_PG_PORT:-15432}"
REDIS_PORT="${PHASE2_REDIS_PORT:-16379}"
PG_USER="${PHASE2_PG_USER:-phase2}"
PG_PASSWORD="${PHASE2_PG_PASSWORD:-phase2pass}"
PG_DB="${PHASE2_PG_DB:-phase2}"

action="${1:-up}"

case "$action" in
  up)
    docker rm -f "$PG_NAME" "$REDIS_NAME" >/dev/null 2>&1 || true
    docker run -d --name "$PG_NAME" \
      -e POSTGRES_USER="$PG_USER" \
      -e POSTGRES_PASSWORD="$PG_PASSWORD" \
      -e POSTGRES_DB="$PG_DB" \
      -p "${PG_PORT}:5432" \
      pgvector/pgvector:pg16 >/dev/null
    docker run -d --name "$REDIS_NAME" \
      -p "${REDIS_PORT}:6379" \
      redis:7-alpine >/dev/null
    for _ in $(seq 1 60); do
      if docker exec "$PG_NAME" pg_isready -U "$PG_USER" -d "$PG_DB" >/dev/null 2>&1 \
        && docker exec "$REDIS_NAME" redis-cli ping 2>/dev/null | grep -q PONG; then
        break
      fi
      sleep 1
    done
    docker exec "$PG_NAME" pg_isready -U "$PG_USER" -d "$PG_DB" >/dev/null
    docker exec "$REDIS_NAME" redis-cli ping >/dev/null
    echo "postgresql+asyncpg://${PG_USER}:${PG_PASSWORD}@127.0.0.1:${PG_PORT}/${PG_DB}"
    echo "redis://127.0.0.1:${REDIS_PORT}/0"
    ;;
  down)
    docker rm -f "$PG_NAME" "$REDIS_NAME" >/dev/null 2>&1 || true
    echo "phase2 infra down"
    ;;
  urls)
    echo "DATABASE_URL=postgresql+asyncpg://${PG_USER}:${PG_PASSWORD}@127.0.0.1:${PG_PORT}/${PG_DB}"
    echo "REDIS_URL=redis://127.0.0.1:${REDIS_PORT}/0"
    echo "CELERY_BROKER_URL=redis://127.0.0.1:${REDIS_PORT}/0"
    echo "CELERY_RESULT_BACKEND=redis://127.0.0.1:${REDIS_PORT}/0"
    ;;
  *)
    echo "usage: $0 up|down|urls" >&2
    exit 2
    ;;
esac
