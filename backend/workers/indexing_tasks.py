from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from dataclasses import dataclass

from backend.db.session import AsyncSessionLocal
from backend.core.config import settings
from backend.core.observability import record_job_transition
from backend.services.email_sync_service import EmailConnectorSyncService
from backend.services.indexing_service import DocumentIngestionService
from backend.services.job_lifecycle import JobLifecycleService
from backend.services.nextcloud_automation_service import NextcloudAutomationService
from backend.services.nextcloud_sync_service import NextcloudConnectorSyncService
from backend.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
_WORKER_PING_CACHE_TTL_SECONDS = 5.0
_worker_ping_cache: dict[str, float | bool] = {"checked_at": 0.0, "available": False}


@dataclass(slots=True)
class EnqueuedTaskHandle:
    id: str


async def _run_logged_background_task(coro, *, label: str) -> None:
    try:
        await coro
    except Exception:
        logger.exception("Background task %s failed", label)


@celery_app.task(bind=True, max_retries=3)
def run_connector_sync_job(self, job_id: str) -> dict[str, int]:
    retry_attempt = int(getattr(self.request, "retries", 0))
    try:
        return asyncio.run(
            _run_connector_sync_job(
                job_id=job_id,
                task_id=self.request.id,
                retry_count=retry_attempt,
            )
        )
    except Exception as exc:
        will_retry = retry_attempt < int(self.max_retries)
        asyncio.run(
            _update_failed_job_state(
                job_id=job_id,
                task_id=self.request.id,
                error_message=str(exc),
                retry_count=retry_attempt + 1 if will_retry else retry_attempt,
                dead_lettered=not will_retry,
            )
        )
        if not will_retry:
            raise

        countdown = min(300, (2**retry_attempt) * 15) + random.randint(0, 5)
        raise self.retry(exc=exc, countdown=countdown)


async def _run_connector_sync_job(
    *, job_id: str, task_id: str | None, retry_count: int = 0
) -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        from backend.db.repo.sync_job import SyncJobRepository

        job_repo = SyncJobRepository(session)
        job = await job_repo.get(job_id)
        if job is None:
            raise ValueError(f"Sync job {job_id} not found")
        JobLifecycleService.mark_running(job, task_id=task_id, retry_count=retry_count)
        await session.commit()

        service = NextcloudConnectorSyncService(session)
        connector = await service.connector_repo.get(job.connector_id)
        if connector is None:
            raise ValueError(f"Connector {job.connector_id} not found")
        if connector.connector_type == "imap":
            result = await EmailConnectorSyncService(session).sync_connector(
                connector,
                full_reindex=bool((job.payload_json or {}).get("full_reindex", False)),
                job=job,
            )
        else:
            result = await service.sync_connector(
                connector,
                full_reindex=bool((job.payload_json or {}).get("full_reindex", False)),
                job=job,
            )
        record_job_transition(job_type=job.job_type, status="succeeded")
        return result


async def _update_failed_job_state(
    *,
    job_id: str,
    task_id: str | None,
    error_message: str,
    retry_count: int,
    dead_lettered: bool,
) -> None:
    async with AsyncSessionLocal() as session:
        from backend.db.repo.sync_job import SyncJobRepository

        job = await SyncJobRepository(session).get(job_id)
        if job is None:
            logger.error("Failed to update retry state; sync job %s not found", job_id)
            return

        if dead_lettered:
            JobLifecycleService.mark_failed(
                job,
                error_message,
                result={
                    **dict(job.result_json or {}),
                    "dead_lettered": True,
                    "last_error": error_message,
                },
                dead_lettered=True,
            )
            record_job_transition(job_type=job.job_type, status="dead_lettered")
            logger.error(
                "Connector sync job dead-lettered",
                extra={"job_id": job_id, "task_id": task_id, "retry_count": retry_count},
            )
        else:
            JobLifecycleService.mark_retrying(
                job,
                error_message,
                retry_count=retry_count,
                task_id=task_id,
            )
            record_job_transition(job_type=job.job_type, status="retrying")
            logger.warning(
                "Connector sync job scheduled for retry",
                extra={"job_id": job_id, "task_id": task_id, "retry_count": retry_count},
            )
        await session.commit()


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def run_document_reindex_task(self, document_id: str) -> str:
    return asyncio.run(_run_document_reindex_task(document_id=document_id))


async def _run_document_reindex_task(*, document_id: str) -> str:
    async with AsyncSessionLocal() as session:
        service = DocumentIngestionService(session)
        document = await service.index_document(document_id)
        await session.commit()
        return str(document.id)


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def enqueue_stale_connector_syncs(self) -> dict[str, int]:
    return asyncio.run(_enqueue_stale_connector_syncs())


async def _enqueue_stale_connector_syncs() -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        summary = await NextcloudAutomationService(session).enqueue_stale_connector_syncs()
        return summary.to_dict()


def _enqueue_eager_task(coro, *, label: str) -> EnqueuedTaskHandle:
    task_id = str(uuid.uuid4())
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
    else:
        loop.create_task(_run_logged_background_task(coro, label=label), name=label)
    return EnqueuedTaskHandle(id=task_id)


def _celery_worker_is_available() -> bool:
    now = time.monotonic()
    checked_at = float(_worker_ping_cache["checked_at"])
    if now - checked_at < _WORKER_PING_CACHE_TTL_SECONDS:
        return bool(_worker_ping_cache["available"])

    available = False
    try:
        responses = celery_app.control.inspect(timeout=0.5).ping()
        available = bool(responses)
    except Exception:
        logger.exception("Celery worker availability check failed")

    _worker_ping_cache["checked_at"] = now
    _worker_ping_cache["available"] = available
    return available


def should_execute_tasks_locally() -> bool:
    if celery_app.conf.task_always_eager:
        return True
    if settings.APP_ENV != "development":
        return False
    return not _celery_worker_is_available()


def enqueue_connector_sync_job(job_id: str):
    if should_execute_tasks_locally():
        task_id = str(uuid.uuid4())
        coro = _run_connector_sync_job(job_id=job_id, task_id=task_id)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
        else:
            loop.create_task(
                _run_logged_background_task(
                    coro, label=f"connector_sync:{job_id}"
                ),
                name=f"connector_sync:{job_id}",
            )
        if not celery_app.conf.task_always_eager:
            logger.warning(
                "No Celery worker detected in development; executing connector sync locally"
            )
        return EnqueuedTaskHandle(id=task_id)
    return run_connector_sync_job.delay(job_id)


def enqueue_document_reindex(document_id: str):
    if should_execute_tasks_locally():
        if not celery_app.conf.task_always_eager:
            logger.warning(
                "No Celery worker detected in development; executing document reindex locally"
            )
        return _enqueue_eager_task(
            _run_document_reindex_task(document_id=document_id),
            label=f"document_reindex:{document_id}",
        )
    return run_document_reindex_task.delay(document_id)


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def run_document_intelligence_extraction_task(self, document_id: str) -> str:
    return asyncio.run(
        _run_document_intelligence_extraction_task(document_id=document_id)
    )


async def _run_document_intelligence_extraction_task(*, document_id: str) -> str:
    if not settings.PRODUCT_INTELLIGENCE_ENABLED:
        return document_id
    async with AsyncSessionLocal() as session:
        service = DocumentIngestionService(session)
        try:
            await service.recompute_product_intelligence(document_id)
            await session.commit()
        except Exception:
            logger.exception(
                "Intelligence extraction task failed document_id=%s", document_id
            )
            await session.rollback()
            raise
    return document_id


def enqueue_document_intelligence(document_id: str) -> EnqueuedTaskHandle:
    if should_execute_tasks_locally():
        if not celery_app.conf.task_always_eager:
            logger.warning(
                "No Celery worker detected in development; running intelligence extraction locally"
            )
        return _enqueue_eager_task(
            _run_document_intelligence_extraction_task(document_id=document_id),
            label=f"document_intelligence:{document_id}",
        )
    async_result = run_document_intelligence_extraction_task.apply_async(
        args=[document_id], countdown=1
    )
    return EnqueuedTaskHandle(id=str(async_result.id))
