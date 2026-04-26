from __future__ import annotations

import asyncio
import logging

from celery import Celery
from celery.signals import worker_ready

from ..ai.ollama_runtime import OllamaRuntimeService
from ..core.config import settings

celery_app = Celery(
    "nextcloud_ai",
    broker=settings.effective_celery_broker_url,
    backend=settings.effective_celery_result_backend,
    include=["backend.workers.indexing_tasks"],
    pool=asyncio,
    concurrency=10
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
    beat_schedule={
        "nextcloud-fallback-sync": {
            "task": "backend.workers.indexing_tasks.enqueue_stale_connector_syncs",
            "schedule": settings.NEXTCLOUD_FALLBACK_SYNC_INTERVAL_SECONDS,
        }
    },
)

logger = logging.getLogger(__name__)


@worker_ready.connect
def warm_ollama_models_on_worker_boot(**_: object) -> None:
    if not settings.ollama_required:
        return

    runtime = OllamaRuntimeService()
    if settings.OLLAMA_BOOTSTRAP_MODE == "ensure":
        status = asyncio.run(runtime.ensure_models_ready())
    else:
        status = asyncio.run(runtime.check_readiness())
    if status.ready:
        logger.info(
            "Celery worker warmed Ollama models: %s",
            ", ".join(status.required_models.values()),
        )
        return

    logger.warning(
        "Celery worker could not prepare Ollama models: %s",
        status.error or ", ".join(status.missing_models),
    )
