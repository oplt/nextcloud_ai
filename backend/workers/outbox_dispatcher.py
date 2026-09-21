"""Drain transactional work_outbox after commit / on a schedule."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.repo.outbox import WorkOutboxRepository
from ..db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

TOPIC_DOCUMENT_INTELLIGENCE = "document_intelligence"


async def dispatch_outbox_batch(
    session: AsyncSession | None = None, *, limit: int = 20
) -> dict[str, int]:
    """Claim pending outbox rows and hand them to topic handlers.

    Broker failures leave the row pending for retry (commit already succeeded).
    """
    owns_session = session is None
    if owns_session:
        session = AsyncSessionLocal()

    assert session is not None
    repo = WorkOutboxRepository(session)
    done = 0
    failed = 0
    retried = 0
    try:
        rows = await repo.claim_batch(limit=limit)
        await session.commit()

        for row in rows:
            try:
                await _dispatch_row(row.topic, dict(row.payload_json or {}))
                async with AsyncSessionLocal() as mark_session:
                    await WorkOutboxRepository(mark_session).mark_done(row.id)
                    await mark_session.commit()
                done += 1
            except Exception as exc:
                logger.exception("Outbox dispatch failed id=%s topic=%s", row.id, row.topic)
                async with AsyncSessionLocal() as mark_session:
                    await WorkOutboxRepository(mark_session).mark_retry(
                        row.id, error=str(exc)
                    )
                    await mark_session.commit()
                retried += 1
                failed += 1
    finally:
        if owns_session:
            await session.close()

    return {"done": done, "failed": failed, "retried": retried, "claimed": done + failed}


async def _dispatch_row(topic: str, payload: dict) -> None:
    if topic == TOPIC_DOCUMENT_INTELLIGENCE:
        document_id = str(payload.get("document_id") or "")
        if not document_id:
            raise ValueError("document_intelligence payload missing document_id")
        from ..workers.indexing_tasks import enqueue_document_intelligence_immediate

        enqueue_document_intelligence_immediate(document_id)
        return
    raise ValueError(f"Unknown outbox topic: {topic}")
