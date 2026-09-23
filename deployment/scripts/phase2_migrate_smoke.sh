#!/usr/bin/env bash
# Phase 2: fresh install + previous-revision upgrade smoke on disposable Postgres.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

PRIOR_REV="${PHASE2_PRIOR_REV:-d4e5f6a7b8c9}"
KEEP_INFRA="${PHASE2_KEEP_INFRA:-0}"

chmod +x deployment/scripts/phase2_infra.sh
mapfile -t URLS < <(bash deployment/scripts/phase2_infra.sh up)
DATABASE_URL="${URLS[0]}"
REDIS_URL="${URLS[1]}"

cleanup() {
  if [[ "$KEEP_INFRA" == "1" ]]; then
    echo "PHASE2_KEEP_INFRA=1 — leaving phase2-pg/phase2-redis"
    return
  fi
  bash deployment/scripts/phase2_infra.sh down >/dev/null
}
trap cleanup EXIT

export DATABASE_URL
export REDIS_URL
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

ALEMBIC=(backend/.venv/bin/alembic -c backend/alembic.ini)

echo "==> Fresh install: upgrade head"
"${ALEMBIC[@]}" upgrade head
HEAD="$("${ALEMBIC[@]}" current 2>/dev/null | awk '{print $1}' | head -1)"
echo "current=$HEAD"
test -n "$HEAD"

echo "==> Seed representative rows at head (survive soft downgrade/upgrade)"
backend/.venv/bin/python - <<'PY'
import asyncio
from uuid import uuid4
from sqlalchemy import text
from backend.db.session import AsyncSessionLocal, dispose_db

async def main() -> None:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO work_outbox
                      (id, topic, payload_json, idempotency_key, status, attempts, available_at, created_at, updated_at)
                    VALUES
                      (:id, 'document_intelligence', CAST(:payload AS jsonb), :key, 'pending', 0, now(), now(), now())
                    ON CONFLICT (idempotency_key) DO NOTHING
                    """
                ),
                {
                    "id": str(uuid4()),
                    "payload": '{"document_id":"phase2-migrate-marker"}',
                    "key": "phase2-migrate-marker",
                },
            )
            await session.commit()
    finally:
        await dispose_db()

asyncio.run(main())
PY

echo "==> Downgrade to prior revision ${PRIOR_REV}"
"${ALEMBIC[@]}" downgrade "$PRIOR_REV"
CUR="$("${ALEMBIC[@]}" current 2>/dev/null | awk '{print $1}' | head -1)"
echo "current=$CUR"
test "$CUR" = "$PRIOR_REV"

echo "==> Upgrade back to head (representative soft upgrade)"
"${ALEMBIC[@]}" upgrade head
CUR="$("${ALEMBIC[@]}" current 2>/dev/null | awk '{print $1}' | head -1)"
echo "current=$CUR"
test "$CUR" = "$HEAD"

echo "==> Verify seeded outbox row survived soft upgrade"
backend/.venv/bin/python - <<'PY'
import asyncio
from sqlalchemy import text
from backend.db.session import AsyncSessionLocal, dispose_db

async def main() -> None:
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT status FROM work_outbox WHERE idempotency_key = :k"),
                {"k": "phase2-migrate-marker"},
            )
            status = result.scalar_one_or_none()
            if status != "pending":
                raise SystemExit(f"expected pending outbox marker, got {status!r}")
            print("marker_ok", status)
    finally:
        await dispose_db()

asyncio.run(main())
PY

echo "==> Second fresh volume path: drop schema + upgrade head"
backend/.venv/bin/python - <<'PY'
import asyncio
from sqlalchemy import text
from backend.db.session import AsyncSessionLocal, dispose_db

async def main() -> None:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("DROP SCHEMA public CASCADE"))
            await session.execute(text("CREATE SCHEMA public"))
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await session.commit()
    finally:
        await dispose_db()

asyncio.run(main())
PY
"${ALEMBIC[@]}" upgrade head
CUR="$("${ALEMBIC[@]}" current 2>/dev/null | awk '{print $1}' | head -1)"
echo "fresh_rebuild_current=$CUR"
test "$CUR" = "$HEAD"

echo "==> Phase 2 migrate smoke OK (head=${HEAD}, prior=${PRIOR_REV})"
