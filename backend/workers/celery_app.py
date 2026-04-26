from __future__ import annotations

import asyncio
import logging
import os
import threading

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown, worker_ready

from ..ai.ollama_runtime import OllamaRuntimeService
from ..core.config import settings
from ..db.session import dispose_db

celery_app = Celery(
    "nextcloud_ai",
    broker=settings.effective_celery_broker_url,
    backend=settings.effective_celery_result_backend,
    include=["backend.workers.indexing_tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_always_eager=settings.celery_task_always_eager,
    task_store_eager_result=settings.celery_task_always_eager,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=3600,
    task_time_limit=3660,
    worker_max_tasks_per_child=100,
    beat_schedule={
        "nextcloud-fallback-sync": {
            "task": "backend.workers.indexing_tasks.enqueue_stale_connector_syncs",
            "schedule": settings.NEXTCLOUD_FALLBACK_SYNC_INTERVAL_SECONDS,
        },
    },
)

logger = logging.getLogger(__name__)


@worker_process_init.connect
def init_worker_process(**kwargs):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(dispose_db())
        logger.info("Worker %s initialized with fresh event loop", os.getpid())
    except Exception:
        logger.warning("Error disposing inherited DB connections", exc_info=True)


@worker_process_shutdown.connect
def shutdown_worker_process(**kwargs):
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            loop.run_until_complete(dispose_db())
            loop.close()
        logger.info("Worker %s shutdown complete", os.getpid())
    except Exception:
        logger.warning("Error during worker shutdown cleanup", exc_info=True)


def _warm_ollama_models() -> None:
    async def warm_models():
        runtime = OllamaRuntimeService()
        if settings.OLLAMA_BOOTSTRAP_MODE == "ensure":
            status = await runtime.ensure_models_ready()
        else:
            status = await runtime.check_readiness()

        if status.ready:
            logger.info("Celery worker warmed Ollama models: %s", ", ".join(status.required_models.values()))
        else:
            logger.warning(
                "Celery worker could not prepare Ollama models: %s",
                status.error or ", ".join(status.missing_models),
                )

    try:
        asyncio.run(warm_models())
    except Exception:
        logger.warning("Ollama warmup failed", exc_info=True)


@worker_ready.connect
def warm_ollama_models_on_worker_boot(**_: object) -> None:
    if not settings.ollama_required:
        return

    threading.Thread(
        target=_warm_ollama_models,
        name="ollama-warmup",
        daemon=True,
    ).start()