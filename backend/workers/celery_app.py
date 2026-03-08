from __future__ import annotations

from celery import Celery

from backend.core.config import settings

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
)
