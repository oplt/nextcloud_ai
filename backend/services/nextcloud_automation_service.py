from __future__ import annotations

import logging
import posixpath
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..connectors.nextcloud.debounce_store import (
    DebounceStore,
    RedisDebounceStore,
)
from ..connectors.nextcloud.schemas import NextcloudWebhookEvent
from ..core.config import settings
from ..db.models import Connector
from ..db.repo.connector import ConnectorRepository
from ..db.repo.document import DocumentRepository
from ..db.repo.sync_job import SyncJobRepository
from .job_service import JobService

logger = logging.getLogger(__name__)

SYNC_EVENT_KEYWORDS = (
    "delete",
    "remove",
    "trash",
    "move",
    "rename",
    "restore",
    "share",
    "permission",
    "folder",
    "directory",
)


@dataclass(slots=True)
class WebhookDispatchResult:
    accepted: bool
    scheduled: bool
    action: str
    connector_id: str | None = None
    document_id: str | None = None
    job_id: str | None = None
    task_id: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "scheduled": self.scheduled,
            "action": self.action,
            "connector_id": self.connector_id,
            "document_id": self.document_id,
            "job_id": self.job_id,
            "task_id": self.task_id,
            "reason": self.reason,
        }


@dataclass(slots=True)
class FallbackSyncSummary:
    scanned: int = 0
    enqueued: int = 0
    skipped_not_stale: int = 0
    skipped_inflight: int = 0
    skipped_debounced: int = 0
    skipped_duplicate_job: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "enqueued": self.enqueued,
            "skipped_not_stale": self.skipped_not_stale,
            "skipped_inflight": self.skipped_inflight,
            "skipped_debounced": self.skipped_debounced,
            "skipped_duplicate_job": self.skipped_duplicate_job,
        }


class NextcloudAutomationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        debounce_store: DebounceStore | None = None,
    ) -> None:
        self.session = session
        self.connector_repo = ConnectorRepository(session)
        self.document_repo = DocumentRepository(session)
        self.sync_job_repo = SyncJobRepository(session)
        self.job_service = JobService(session)
        self.debounce_store = debounce_store or RedisDebounceStore(
            settings.nextcloud_event_redis_url
        )

    async def dispatch_webhook_event(
        self, event: NextcloudWebhookEvent
    ) -> WebhookDispatchResult:
        connector = await self._resolve_connector(event)
        if connector is None:
            return WebhookDispatchResult(
                accepted=True,
                scheduled=False,
                action="ignored",
                reason="connector_not_resolved",
            )

        if not await self._acquire_debounce(
            key=self._webhook_debounce_key(connector.id, event),
            ttl_seconds=settings.NEXTCLOUD_WEBHOOK_DEBOUNCE_SECONDS,
        ):
            return WebhookDispatchResult(
                accepted=True,
                scheduled=False,
                action="ignored",
                connector_id=str(connector.id),
                reason="debounced",
            )

        normalized_path = self._normalize_path(event.path)
        action = await self._select_webhook_action(connector, event, normalized_path)
        if action == "reindex" and normalized_path is not None:
            from ..workers.indexing_tasks import enqueue_document_reindex

            document = await self.document_repo.get_by_connector_and_file_path(
                connector.id, normalized_path
            )
            if document is not None:
                task = enqueue_document_reindex(str(document.id))
                return WebhookDispatchResult(
                    accepted=True,
                    scheduled=True,
                    action="reindex",
                    connector_id=str(connector.id),
                    document_id=str(document.id),
                    task_id=task.id,
                )

        reservation = await self.job_service.reserve_sync_job(
            connector_id=str(connector.id),
            requested_by=None,
            full_reindex=False,
            job_key=self._webhook_job_key(connector.id, event, normalized_path),
            payload_json={
                "trigger": "nextcloud_webhook",
                "event": event.event,
                "path": normalized_path,
                "file_id": event.file_id,
                "subject": event.subject,
                "actor": event.actor,
            },
        )
        if not reservation.created:
            return WebhookDispatchResult(
                accepted=True,
                scheduled=False,
                action="sync",
                connector_id=str(connector.id),
                job_id=str(reservation.job.id),
                task_id=reservation.job.worker_task_id,
                reason="duplicate_job",
            )

        from ..workers.indexing_tasks import enqueue_connector_sync_job

        task = enqueue_connector_sync_job(str(reservation.job.id))
        reservation.job.worker_task_id = task.id
        await self.session.commit()
        await self.session.refresh(reservation.job)
        return WebhookDispatchResult(
            accepted=True,
            scheduled=True,
            action="sync",
            connector_id=str(connector.id),
            job_id=str(reservation.job.id),
            task_id=task.id,
        )

    async def enqueue_stale_connector_syncs(
        self, *, now: datetime | None = None
    ) -> FallbackSyncSummary:
        current_time = now or datetime.now(timezone.utc)
        summary = FallbackSyncSummary()
        connectors = await self.connector_repo.list_active()

        for connector in connectors:
            if connector.connector_type != "nextcloud":
                continue
            summary.scanned += 1

            if not self._connector_is_stale(connector, current_time):
                summary.skipped_not_stale += 1
                continue

            latest_job = await self.sync_job_repo.get_latest_for_connector(connector.id)
            if latest_job is not None and latest_job.status in {"queued", "running"}:
                summary.skipped_inflight += 1
                continue

            debounce_key = self._fallback_debounce_key(connector.id, current_time)
            if not await self._acquire_debounce(
                key=debounce_key,
                ttl_seconds=settings.NEXTCLOUD_FALLBACK_SYNC_INTERVAL_SECONDS * 2,
            ):
                summary.skipped_debounced += 1
                continue

            reservation = await self.job_service.reserve_sync_job(
                connector_id=str(connector.id),
                requested_by=None,
                full_reindex=False,
                job_key=debounce_key,
                payload_json={"trigger": "fallback_poll"},
            )
            if not reservation.created:
                summary.skipped_duplicate_job += 1
                continue

            from ..workers.indexing_tasks import enqueue_connector_sync_job

            task = enqueue_connector_sync_job(str(reservation.job.id))
            reservation.job.worker_task_id = task.id
            await self.session.commit()
            await self.session.refresh(reservation.job)
            summary.enqueued += 1

        return summary

    async def _resolve_connector(
        self, event: NextcloudWebhookEvent
    ) -> Connector | None:
        if event.connector_id:
            connector = await self.connector_repo.get(event.connector_id)
            if connector is not None and connector.is_active:
                return connector

        if event.base_url and event.username:
            connector = await self.connector_repo.get_active_by_base_url_and_username(
                base_url=event.base_url,
                username=event.username,
            )
            if connector is not None:
                return connector

        active_connectors = [
            connector
            for connector in await self.connector_repo.list_active()
            if connector.connector_type == "nextcloud"
        ]
        if len(active_connectors) == 1:
            return active_connectors[0]
        return None

    async def _select_webhook_action(
        self,
        connector: Connector,
        event: NextcloudWebhookEvent,
        normalized_path: str | None,
    ) -> str:
        event_name = event.event.lower()
        if event.is_directory or normalized_path is None:
            return "sync"
        if any(keyword in event_name for keyword in SYNC_EVENT_KEYWORDS):
            return "sync"

        document = await self.document_repo.get_by_connector_and_file_path(
            connector.id, normalized_path
        )
        if document is None:
            return "sync"
        return "reindex"

    async def _acquire_debounce(self, *, key: str, ttl_seconds: int) -> bool:
        try:
            return await self.debounce_store.acquire(key, ttl_seconds)
        except Exception:
            logger.exception("Redis debounce failed for key=%s; proceeding without it", key)
            return True

    @staticmethod
    def _normalize_path(path: str | None) -> str | None:
        if not path:
            return None
        stripped = path.strip()
        if not stripped:
            return None
        normalized = stripped if stripped.startswith("/") else f"/{stripped}"
        return posixpath.normpath(normalized)

    @staticmethod
    def _stable_bucket(seconds: int, now: datetime) -> int:
        return int(now.timestamp()) // max(seconds, 1)

    def _webhook_job_key(
        self,
        connector_id: UUID,
        event: NextcloudWebhookEvent,
        normalized_path: str | None,
    ) -> str:
        event_time = event.timestamp or datetime.now(timezone.utc)
        bucket = self._stable_bucket(settings.NEXTCLOUD_WEBHOOK_DEBOUNCE_SECONDS, event_time)
        return (
            f"webhook:{connector_id}:{event.event.lower()}:{normalized_path or '-'}:{bucket}"
        )

    def _webhook_debounce_key(
        self, connector_id: UUID, event: NextcloudWebhookEvent
    ) -> str:
        normalized_path = self._normalize_path(event.path) or "-"
        event_time = event.timestamp or datetime.now(timezone.utc)
        bucket = self._stable_bucket(settings.NEXTCLOUD_WEBHOOK_DEBOUNCE_SECONDS, event_time)
        return (
            f"webhook-debounce:{connector_id}:{event.event.lower()}:{normalized_path}:{bucket}"
        )

    def _fallback_debounce_key(self, connector_id: UUID, now: datetime) -> str:
        bucket = self._stable_bucket(settings.NEXTCLOUD_FALLBACK_STALE_AFTER_SECONDS, now)
        return f"fallback:{connector_id}:{bucket}"

    @staticmethod
    def _connector_is_stale(connector: Connector, now: datetime) -> bool:
        if connector.last_sync_at is None:
            return True
        return connector.last_sync_at <= now - timedelta(
            seconds=settings.NEXTCLOUD_FALLBACK_STALE_AFTER_SECONDS
        )
