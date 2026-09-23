"""Phase 2: real Postgres outbox/lease/generation integration smoke.

Starts no infra itself — expects DATABASE_URL (+ optional Redis) already set,
schema at Alembic head. Prefer: `make phase2-outbox-smoke`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text

from backend.db.models import Connector, Document, SyncJob, WorkOutbox
from backend.db.repo.outbox import WorkOutboxRepository
from backend.db.repo.sync_job import SyncJobRepository
from backend.db.session import AsyncSessionLocal, dispose_db
from backend.ingestion.index_versions import (
    StaleIndexGenerationError,
    assert_publish_allowed,
    begin_index_attempt,
    mark_published,
)
from backend.services.job_lifecycle import JobLifecycleService
from backend.workers import outbox_dispatcher


async def _seed_connector_document() -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as session:
        connector = Connector(
            connector_type="nextcloud",
            display_name="phase2-smoke",
            base_url="https://nc.example",
            username="phase2",
            encrypted_secret="unused",
            root_path="/",
            is_active=True,
            status="ready",
        )
        session.add(connector)
        await session.flush()
        document = Document(
            connector_id=connector.id,
            external_id=f"phase2-{uuid.uuid4()}",
            file_path="/phase2/smoke.txt",
            file_name="smoke.txt",
            source_type="nextcloud",
            sync_status="synced",
            parse_status="indexed",
            index_generation=0,
            published_generation=0,
            version_tag="v1",
            allowed_user_ids=[],
            allowed_group_ids=[],
        )
        session.add(document)
        await session.commit()
        return connector.id, document.id


async def _race_generations(document_id: uuid.UUID) -> dict[str, Any]:
    """Worker A publishes gen N; worker B starts gen N+1; A cannot publish stale."""
    async with AsyncSessionLocal() as session_a:
        document_a = await session_a.get(Document, document_id)
        assert document_a is not None
        attempt_a = await begin_index_attempt(session_a, document_a)
        await session_a.commit()

    async with AsyncSessionLocal() as session_b:
        document_b = await session_b.get(Document, document_id)
        assert document_b is not None
        attempt_b = await begin_index_attempt(session_b, document_b)
        mark_published(document_b, attempt_b)
        await session_b.commit()

    async with AsyncSessionLocal() as session_a2:
        document_stale = await session_a2.get(Document, document_id)
        assert document_stale is not None
        try:
            assert_publish_allowed(document_stale, attempt_a)
            raised = False
        except StaleIndexGenerationError:
            raised = True
        if not raised:
            raise RuntimeError("stale generation publish was allowed")
        if int(document_stale.published_generation) != attempt_b.generation:
            raise RuntimeError("newer generation lost the race")
        return {
            "stale_generation": attempt_a.generation,
            "winner_generation": attempt_b.generation,
            "published_generation": document_stale.published_generation,
        }


async def _outbox_broker_fail_then_redeliver(document_id: uuid.UUID) -> dict[str, Any]:
    key = f"document_intelligence:{document_id}:gen:1"
    async with AsyncSessionLocal() as session:
        repo = WorkOutboxRepository(session)
        await repo.enqueue(
            topic=outbox_dispatcher.TOPIC_DOCUMENT_INTELLIGENCE,
            payload={
                "document_id": str(document_id),
                "published_generation": 1,
            },
            idempotency_key=key,
        )
        # Idempotent re-enqueue must not create a second row.
        await repo.enqueue(
            topic=outbox_dispatcher.TOPIC_DOCUMENT_INTELLIGENCE,
            payload={"document_id": str(document_id), "published_generation": 1},
            idempotency_key=key,
        )
        await session.commit()
        count = (
            (
                await session.execute(
                    select(WorkOutbox).where(WorkOutbox.idempotency_key == key)
                )
            )
            .scalars()
            .all()
        )
        if len(count) != 1:
            raise RuntimeError(f"idempotency failed: {len(count)} rows")

    fail_calls = {"n": 0}
    delivered: list[dict[str, Any]] = []

    async def boom(topic: str, payload: dict) -> None:
        fail_calls["n"] += 1
        raise RuntimeError("simulated broker failure")

    async def capture(topic: str, payload: dict) -> None:
        delivered.append({"topic": topic, "payload": payload})

    original = outbox_dispatcher._dispatch_row
    outbox_dispatcher._dispatch_row = boom  # type: ignore[assignment]
    try:
        result_fail = await outbox_dispatcher.dispatch_outbox_batch()
    finally:
        outbox_dispatcher._dispatch_row = original  # type: ignore[assignment]

    if result_fail.get("failed", 0) < 1:
        raise RuntimeError(f"expected broker failure path, got {result_fail}")

    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(WorkOutbox).where(WorkOutbox.idempotency_key == key)
            )
        ).scalar_one()
        if row.status != "pending":
            raise RuntimeError(f"expected pending after broker fail, got {row.status}")
        # Make immediately available (skip retry delay).
        row.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()

    outbox_dispatcher._dispatch_row = capture  # type: ignore[assignment]
    try:
        result_ok = await outbox_dispatcher.dispatch_outbox_batch()
    finally:
        outbox_dispatcher._dispatch_row = original  # type: ignore[assignment]

    if result_ok.get("done", 0) < 1:
        raise RuntimeError(f"redelivery did not complete: {result_ok}")
    if not delivered:
        raise RuntimeError("redelivery handler never called")
    if delivered[0]["payload"].get("published_generation") != 1:
        raise RuntimeError("redelivery lost published_generation")

    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(WorkOutbox).where(WorkOutbox.idempotency_key == key)
            )
        ).scalar_one()
        if row.status != "done":
            raise RuntimeError(f"expected done after redelivery, got {row.status}")

    return {
        "broker_failures": fail_calls["n"],
        "fail_dispatch": result_fail,
        "ok_dispatch": result_ok,
        "delivered_generation": delivered[0]["payload"].get("published_generation"),
    }


async def _outbox_reclaim_stale_processing() -> dict[str, Any]:
    key = f"phase2-stale-processing:{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        row = WorkOutbox(
            topic=outbox_dispatcher.TOPIC_DOCUMENT_INTELLIGENCE,
            payload_json={"document_id": str(uuid.uuid4())},
            idempotency_key=key,
            status="processing",
            attempts=1,
            available_at=now - timedelta(hours=1),
            created_at=now - timedelta(hours=1),
            updated_at=now - timedelta(hours=1),
        )
        session.add(row)
        await session.commit()
        row_id = row.id

    original = outbox_dispatcher._dispatch_row
    try:
        async with AsyncSessionLocal() as session:
            repo = WorkOutboxRepository(session)
            claimed = await repo.claim_batch(limit=5, processing_timeout_seconds=30)
            await session.commit()
            ids = {str(item.id) for item in claimed}
        if str(row_id) not in ids:
            raise RuntimeError("abandoned processing row was not reclaimed")
    finally:
        outbox_dispatcher._dispatch_row = original  # type: ignore[assignment]

    return {"reclaimed_id": str(row_id)}


async def _lease_expiry_spares_healthy(connector_id: uuid.UUID) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        expired = SyncJob(
            connector_id=connector_id,
            job_key=f"phase2-expired-{uuid.uuid4()}",
            job_type="sync",
            status="queued",
        )
        healthy = SyncJob(
            connector_id=connector_id,
            job_key=f"phase2-healthy-{uuid.uuid4()}",
            job_type="sync",
            status="queued",
        )
        no_lease = SyncJob(
            connector_id=connector_id,
            job_key=f"phase2-nolease-{uuid.uuid4()}",
            job_type="sync",
            status="queued",
        )
        session.add_all([expired, healthy, no_lease])
        await session.flush()
        JobLifecycleService.mark_running(
            expired, task_id="worker-old", lease_owner="worker-old"
        )
        expired.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        JobLifecycleService.mark_running(
            healthy, task_id="worker-live", lease_owner="worker-live"
        )
        # Simulate API-era unknown lease: running without expiry must survive.
        no_lease.status = "running"
        no_lease.started_at = datetime.now(timezone.utc)
        no_lease.lease_owner = None
        no_lease.lease_expires_at = None
        await session.commit()
        expired_id, healthy_id, no_lease_id = expired.id, healthy.id, no_lease.id

    async with AsyncSessionLocal() as session:
        failed = await SyncJobRepository(session).fail_expired_leases(
            message="Job lease expired without heartbeat"
        )
        # fail_expired commits internally

    async with AsyncSessionLocal() as session:
        exp = await session.get(SyncJob, expired_id)
        heal = await session.get(SyncJob, healthy_id)
        bare = await session.get(SyncJob, no_lease_id)
        assert exp is not None and heal is not None and bare is not None
        if exp.status != "failed":
            raise RuntimeError(f"expired lease not failed: {exp.status}")
        if heal.status != "running":
            raise RuntimeError(f"healthy lease killed: {heal.status}")
        if bare.status != "running":
            raise RuntimeError(f"no-lease running job killed on cleanup: {bare.status}")
        return {
            "failed_count": failed,
            "expired_status": exp.status,
            "healthy_status": heal.status,
            "no_lease_status": bare.status,
        }


async def _redis_ping() -> dict[str, Any]:
    import os

    url = os.environ.get("REDIS_URL") or os.environ.get("CELERY_BROKER_URL")
    if not url:
        return {"redis": "skipped", "reason": "REDIS_URL unset"}
    import redis

    client = redis.Redis.from_url(url, socket_connect_timeout=2)
    pong = client.ping()
    client.close()
    if not pong:
        raise RuntimeError("redis ping failed")
    return {"redis": "ok"}


async def _run() -> dict[str, Any]:
    try:
        await _redis_ping()
        # Ensure extension exists on disposable volumes.
        async with AsyncSessionLocal() as session:
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await session.commit()

        connector_id, document_id = await _seed_connector_document()
        race = await _race_generations(document_id)
        outbox = await _outbox_broker_fail_then_redeliver(document_id)
        reclaim = await _outbox_reclaim_stale_processing()
        leases = await _lease_expiry_spares_healthy(connector_id)
        redis_info = await _redis_ping()
        return {
            "document_id": str(document_id),
            "connector_id": str(connector_id),
            "generation_race": race,
            "outbox": outbox,
            "reclaim": reclaim,
            "leases": leases,
            "redis": redis_info,
        }
    finally:
        await dispose_db()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        report = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **report}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
