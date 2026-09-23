from __future__ import annotations

import asyncio
import logging
import os
import random
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from ..db.session import AsyncSessionLocal
from ..core.config import settings
from ..core.observability import record_job_transition
from ..services.email_sync_service import EmailConnectorSyncService
from ..services.indexing_service import DocumentIngestionService
from ..services.job_lifecycle import JobLifecycleService
from ..services.nextcloud_automation_service import NextcloudAutomationService
from ..services.nextcloud_sync_service import NextcloudConnectorSyncService
from .celery_app import celery_app

logger = logging.getLogger(__name__)

# Cache for worker availability - reduced TTL for faster detection
_WORKER_PING_CACHE_TTL_SECONDS = 2.0  # Reduced from 5s for faster failover
_worker_ping_cache: dict[str, float | bool] = {"checked_at": 0.0, "available": False}

# Thread-local storage for event loops - FIXED per-process management
_task_loop: Optional[asyncio.AbstractEventLoop] = None
_task_loop_pid: Optional[int] = None


def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    global _task_loop, _task_loop_pid

    current_pid = os.getpid()

    if _task_loop_pid == current_pid and _task_loop and not _task_loop.is_closed():
        return _task_loop

    _task_loop = asyncio.new_event_loop()
    _task_loop_pid = current_pid
    asyncio.set_event_loop(_task_loop)
    logger.debug("Created Celery task event loop for process %s", current_pid)
    return _task_loop


def initialize_worker_loop() -> asyncio.AbstractEventLoop:
    """Return the single resource-owning loop for this worker process."""
    return _get_or_create_event_loop()


def close_worker_loop() -> None:
    """Close and forget the process-owned loop after resource shutdown."""
    global _task_loop, _task_loop_pid
    if _task_loop is not None and not _task_loop.is_closed():
        _task_loop.close()
    try:
        asyncio.set_event_loop(None)
    except RuntimeError:
        pass
    _task_loop = None
    _task_loop_pid = None


def _run_in_worker_loop(coro):
    """Run a coroutine on the process-owned worker loop.

    Never re-await an already-started coroutine after an arbitrary RuntimeError:
    that object is exhausted. Only recreate the loop for closed-loop failures,
    and only when a fresh coroutine factory is not available — callers must not
    rely on retry of the same coro instance.
    """
    global _task_loop, _task_loop_pid

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = _get_or_create_event_loop()
        try:
            return loop.run_until_complete(coro)
        except RuntimeError as exc:
            message = str(exc).lower()
            loop_dead = (
                loop.is_closed()
                or "event loop is closed" in message
                or "no current event loop" in message
            )
            if not loop_dead:
                # Preserve business RuntimeErrors (and any other non-loop failures).
                raise
            logger.warning(
                "Celery task event loop closed mid-task; recreating for next tasks",
                exc_info=True,
            )
            if not loop.is_closed():
                loop.close()
            _task_loop = None
            _task_loop_pid = None
            # Do not rerun the exhausted coroutine.
            raise

    raise RuntimeError(
        "Celery sync task entered an already-running event loop; await directly instead."
    )


@celery_app.task(bind=True, max_retries=3, soft_time_limit=3600, time_limit=3660)
def run_connector_sync_job(self, job_id: str) -> dict[str, int]:
    """Run connector sync job with improved retry handling"""
    retry_attempt = int(getattr(self.request, "retries", 0))

    try:
        return _run_in_worker_loop(
            _run_connector_sync_job(
                job_id=job_id,
                task_id=self.request.id,
                retry_count=retry_attempt,
            )
        )
    except Exception as exc:
        will_retry = retry_attempt < int(self.max_retries)

        # Log error with context
        logger.error(
            f"Connector sync job {job_id} failed (attempt {retry_attempt + 1}/{self.max_retries}): {exc}",
            exc_info=True,
        )

        # Update job state asynchronously
        _run_in_worker_loop(
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

        # Exponential backoff with jitter - optimized
        countdown = min(300, (2**retry_attempt) * 10) + random.randint(0, 5)
        logger.info(f"Retrying job {job_id} in {countdown} seconds")
        raise self.retry(exc=exc, countdown=countdown)


async def _run_connector_sync_job(
    *, job_id: str, task_id: str | None, retry_count: int = 0
) -> dict[str, int]:
    """Async implementation of connector sync job"""
    async with AsyncSessionLocal() as session:
        from ..db.repo.sync_job import SyncJobRepository

        # Optimize: Use connection for all operations
        job_repo = SyncJobRepository(session)
        job = await job_repo.get(job_id)
        if job is None:
            raise ValueError(f"Sync job {job_id} not found")

        JobLifecycleService.mark_running(job, task_id=task_id, retry_count=retry_count)
        await session.flush()  # Flush but don't commit yet

        # Determine service based on connector type
        service = NextcloudConnectorSyncService(session)
        connector = await service.connector_repo.get(job.connector_id)

        if connector is None:
            raise ValueError(f"Connector {job.connector_id} not found")

        full_reindex = bool((job.payload_json or {}).get("full_reindex", False))

        # Execute sync with timeout protection
        try:
            if connector.connector_type == "imap":
                sync_timeout = getattr(settings, "SYNC_TIMEOUT_SECONDS", 900)
                result = await asyncio.wait_for(
                    EmailConnectorSyncService(session).sync_connector(
                        connector, full_reindex=full_reindex, job=job
                    ),
                    timeout=sync_timeout,
                )
            else:
                sync_timeout = getattr(settings, "SYNC_TIMEOUT_SECONDS", 900)
                result = await asyncio.wait_for(
                    service.sync_connector(
                        connector, full_reindex=full_reindex, job=job
                    ),
                    timeout=sync_timeout,
                )
        except asyncio.TimeoutError:
            logger.error(f"Sync job {job_id} timed out after {sync_timeout}s")
            raise

        await session.commit()
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
    """Update job state on failure - optimized with connection pool reuse"""
    async with AsyncSessionLocal() as session:
        from ..db.repo.sync_job import SyncJobRepository

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
                extra={
                    "job_id": job_id,
                    "task_id": task_id,
                    "retry_count": retry_count,
                },
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
                extra={
                    "job_id": job_id,
                    "task_id": task_id,
                    "retry_count": retry_count,
                },
            )
        await session.commit()


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=300,  # 5 minutes for reindex
)
def run_document_reindex_task(self, document_id: str) -> str:
    """Reindex a single document"""
    return _run_in_worker_loop(_run_document_reindex_task(document_id=document_id))


async def _run_document_reindex_task(*, document_id: str) -> str:
    """Async implementation of document reindexing"""
    async with AsyncSessionLocal() as session:
        service = DocumentIngestionService(session)
        document = await service.index_document(document_id)
        await session.commit()
    try:
        from .outbox_dispatcher import dispatch_outbox_batch

        await dispatch_outbox_batch()
    except Exception:
        logger.exception(
            "Outbox dispatch after reindex failed document_id=%s", document_id
        )
    return str(document.id)


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=600,  # 10 minutes
)
def enqueue_stale_connector_syncs(self) -> dict[str, int]:
    """Enqueue sync jobs for stale connectors"""
    return _run_in_worker_loop(_enqueue_stale_connector_syncs())


async def _enqueue_stale_connector_syncs() -> dict[str, int]:
    """Async implementation of stale connector sync"""
    async with AsyncSessionLocal() as session:
        # Optimize with connection reuse
        summary = await NextcloudAutomationService(
            session
        ).enqueue_stale_connector_syncs()
        await session.commit()
        return summary.to_dict()


def _enqueue_eager_task(coro, *, label: str):
    """Enqueue task for local execution - fixed event loop handling"""
    task_id = str(uuid.uuid4())

    async def wrapped():
        try:
            await coro
        except Exception as e:
            logger.error(f"Eager task {label} failed: {e}", exc_info=True)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(wrapped(), name=label)
    except RuntimeError:
        # No running loop, create one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(wrapped())
        finally:
            loop.close()

    return EnqueuedTaskHandle(id=task_id)


def _celery_worker_is_available() -> bool:
    """Cached worker ping for development auto-local mode only.

    Never called from production request paths when CELERY_LOCAL_MODE=never
    or APP_ENV is staging/production.
    """
    now = time.monotonic()
    checked_at = float(_worker_ping_cache["checked_at"])

    if now - checked_at < _WORKER_PING_CACHE_TTL_SECONDS:
        return bool(_worker_ping_cache["available"])

    available = False
    try:
        responses = celery_app.control.inspect(timeout=0.5).ping()
        available = bool(responses and len(responses) > 0)
    except Exception:
        logger.debug("Celery worker availability check failed")

    _worker_ping_cache["checked_at"] = now
    _worker_ping_cache["available"] = available
    return available


def should_execute_tasks_locally() -> bool:
    """Decide in-process task execution without blocking prod on broker ping."""
    if celery_app.conf.task_always_eager:
        return True
    mode = settings.CELERY_LOCAL_MODE
    if mode == "always":
        return True
    if mode == "never":
        return False
    # auto: only in development, with a cached ping (not on every request forever).
    if settings.APP_ENV != "development":
        return False
    return not _celery_worker_is_available()


def enqueue_connector_sync_job(job_id: str):
    """Enqueue connector sync job with improved performance"""
    if should_execute_tasks_locally():
        if not celery_app.conf.task_always_eager:
            logger.info(f"Executing connector sync {job_id} locally (no Celery worker)")
        task_id = str(uuid.uuid4())
        coro = _run_connector_sync_job(job_id=job_id, task_id=task_id)
        return _enqueue_eager_task(coro, label=f"connector_sync:{job_id}")

    # Use apply_async with low latency
    return run_connector_sync_job.apply_async(args=[job_id], priority=5)


def enqueue_document_reindex(document_id: str):
    """Enqueue document reindex task"""
    if should_execute_tasks_locally():
        if not celery_app.conf.task_always_eager:
            logger.info(
                f"Executing document reindex {document_id} locally (no Celery worker)"
            )
        return _enqueue_eager_task(
            _run_document_reindex_task(document_id=document_id),
            label=f"document_reindex:{document_id}",
        )
    return run_document_reindex_task.apply_async(args=[document_id], priority=8)


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=1800,  # 30 minutes for intelligence extraction
)
def run_document_intelligence_extraction_task(
    self, document_id: str, expected_generation: int | None = None
) -> str:
    """Run document intelligence extraction"""
    return _run_in_worker_loop(
        _run_document_intelligence_extraction_task(
            document_id=document_id,
            expected_generation=expected_generation,
        )
    )


async def _run_document_intelligence_extraction_task(
    *, document_id: str, expected_generation: int | None = None
) -> str:
    """Async implementation of intelligence extraction"""
    if not settings.PRODUCT_INTELLIGENCE_ENABLED:
        return document_id

    async with AsyncSessionLocal() as session:
        service = DocumentIngestionService(session)
        try:
            if expected_generation is not None:
                document = await service.document_repo.get_for_update(document_id)
                if document is None:
                    raise ValueError(f"Document {document_id} not found")
                current_generation = int(document.published_generation or 0)
                if current_generation != expected_generation:
                    logger.info(
                        "Skipping stale intelligence task document_id=%s expected_generation=%s current_generation=%s",
                        document_id,
                        expected_generation,
                        current_generation,
                    )
                    return document_id
                completed_generation = int(
                    (document.metadata_json or {}).get(
                        "intelligence_published_generation", -1
                    )
                )
                if completed_generation == expected_generation:
                    logger.info(
                        "Skipping already-applied intelligence task document_id=%s generation=%s",
                        document_id,
                        expected_generation,
                    )
                    return document_id
            await service.recompute_product_intelligence(document_id)
            if expected_generation is not None:
                document.metadata_json = {
                    **dict(document.metadata_json or {}),
                    "intelligence_published_generation": expected_generation,
                }
            await session.commit()
            logger.info(
                "Successfully completed intelligence extraction for document_id=%s",
                document_id,
            )
        except Exception:
            logger.exception(
                "Intelligence extraction task failed document_id=%s", document_id
            )
            await session.rollback()
            raise
    return document_id


def enqueue_document_intelligence(document_id: str):
    """Deprecated direct enqueue: prefer transactional outbox.

    Kept for compatibility. Prefer ``enqueue_document_intelligence_immediate``
    from the outbox dispatcher after commit.
    """
    return enqueue_document_intelligence_immediate(document_id)


def enqueue_document_intelligence_immediate(
    document_id: str, *, expected_generation: int | None = None
):
    """Enqueue intelligence extraction after the source transaction committed."""
    if should_execute_tasks_locally():
        if not celery_app.conf.task_always_eager:
            logger.info(f"Executing intelligence extraction {document_id} locally")
        return _enqueue_eager_task(
            _run_document_intelligence_extraction_task(
                document_id=document_id,
                expected_generation=expected_generation,
            ),
            label=f"document_intelligence:{document_id}",
        )

    async_result = run_document_intelligence_extraction_task.apply_async(
        kwargs={
            "document_id": document_id,
            "expected_generation": expected_generation,
        },
        priority=9,
    )
    return EnqueuedTaskHandle(id=str(async_result.id))


@celery_app.task(name="backend.workers.indexing_tasks.dispatch_work_outbox")
def dispatch_work_outbox() -> dict[str, int]:
    from .outbox_dispatcher import dispatch_outbox_batch

    return _run_in_worker_loop(dispatch_outbox_batch())


@celery_app.task(name="backend.workers.indexing_tasks.fail_expired_job_leases")
def fail_expired_job_leases() -> dict[str, int]:
    async def _run() -> dict[str, int]:
        async with AsyncSessionLocal() as session:
            from ..db.repo.sync_job import SyncJobRepository

            count = await SyncJobRepository(session).fail_expired_leases(
                message="Job lease expired without heartbeat"
            )
            return {"failed": count}

    return _run_in_worker_loop(_run())


@celery_app.task(name="backend.workers.indexing_tasks.cleanup_stale_connections")
def cleanup_stale_connections():
    """Deprecated no-op retained for queued/external drain.

    Connection recycling is handled by SQLAlchemy pool_recycle/pool_pre_ping.
    Do not terminate PostgreSQL idle backends globally. Keep registered through
    one release after confirming no beat/external callers enqueue this name;
    then remove the task registration.
    """
    logger.debug("Skipping global PostgreSQL idle connection cleanup (deprecated task)")
    return {"skipped": True, "deprecated": True}


@dataclass
class EnqueuedTaskHandle:
    """Handle for enqueued tasks"""

    id: str

    def get(self, timeout=None):
        """Get task result - for compatibility with Celery AsyncResult"""
        # In eager mode, we've already executed
        return None
