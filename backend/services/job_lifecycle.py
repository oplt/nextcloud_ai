from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.db.models import SyncJob


class JobLifecycleService:
    @staticmethod
    def mark_running(
        job: SyncJob, *, task_id: str | None = None, total: int | None = None
    ) -> SyncJob:
        job.status = "running"
        job.worker_task_id = task_id
        job.started_at = datetime.now(timezone.utc)
        if total is not None:
            job.progress_total = total
            job.progress_completed = 0
        return job

    @staticmethod
    def advance(job: SyncJob, completed: int) -> SyncJob:
        job.progress_completed = completed
        return job

    @staticmethod
    def mark_succeeded(job: SyncJob, result: dict[str, Any]) -> SyncJob:
        job.status = "succeeded"
        job.completed_at = datetime.now(timezone.utc)
        job.result_json = result
        return job

    @staticmethod
    def mark_failed(job: SyncJob, message: str) -> SyncJob:
        job.status = "failed"
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = message
        return job
