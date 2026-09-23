from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import WorkOutbox
from .base import BaseRepository


class WorkOutboxRepository(BaseRepository[WorkOutbox]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, WorkOutbox)

    async def enqueue(
        self,
        *,
        topic: str,
        payload: dict,
        idempotency_key: str,
        available_at: datetime | None = None,
    ) -> WorkOutbox:
        """Insert pending work; ignore conflict on idempotency key (at-least-once)."""
        now = datetime.now(timezone.utc)
        stmt = (
            insert(WorkOutbox)
            .values(
                id=uuid.uuid4(),
                topic=topic,
                payload_json=payload,
                idempotency_key=idempotency_key,
                status="pending",
                attempts=0,
                available_at=available_at or now,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(WorkOutbox)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is not None:
            await self.session.flush()
            return row
        existing = await self.session.execute(
            select(WorkOutbox).where(WorkOutbox.idempotency_key == idempotency_key)
        )
        return existing.scalar_one()

    async def claim_batch(
        self, *, limit: int = 20, processing_timeout_seconds: int = 300
    ) -> list[WorkOutbox]:
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=max(1, processing_timeout_seconds))
        result = await self.session.execute(
            select(WorkOutbox)
            .where(
                or_(
                    and_(
                        WorkOutbox.status == "pending",
                        WorkOutbox.available_at <= now,
                    ),
                    and_(
                        WorkOutbox.status == "processing",
                        WorkOutbox.updated_at < stale_before,
                    ),
                )
            )
            .order_by(WorkOutbox.available_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = list(result.scalars().all())
        for row in rows:
            row.status = "processing"
            row.attempts = int(row.attempts or 0) + 1
            row.updated_at = now
        if rows:
            await self.session.flush()
        return rows

    async def mark_done(self, row_id: UUID | str) -> None:
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(WorkOutbox)
            .where(WorkOutbox.id == row_id)
            .values(status="done", processed_at=now, updated_at=now, last_error=None)
        )

    async def mark_retry(
        self,
        row_id: UUID | str,
        *,
        error: str,
        delay_seconds: int = 30,
        max_attempts: int = 20,
    ) -> None:
        now = datetime.now(timezone.utc)
        row = await self.get(row_id)
        if row is None:
            return
        if int(row.attempts or 0) >= max_attempts:
            row.status = "failed"
            row.last_error = error
            row.updated_at = now
            row.processed_at = now
        else:
            row.status = "pending"
            row.last_error = error
            row.available_at = now + timedelta(seconds=delay_seconds)
            row.updated_at = now
        await self.session.flush()
