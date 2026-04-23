from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.db.models import SyncJob


class JobLifecycleService:
    @staticmethod
    def mark_running(
        job: SyncJob,
        *,
        task_id: str | None = None,
        total: int | None = None,
        retry_count: int | None = None,
    ) -> SyncJob:
        job.status = "running"
        if task_id is not None:
            job.worker_task_id = task_id
        if retry_count is not None:
            job.retry_count = retry_count
        job.started_at = datetime.now(timezone.utc)
        job.completed_at = None
        job.error_message = None
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
        job.error_message = None
        return job

    @staticmethod
    def mark_retrying(
        job: SyncJob,
        message: str,
        *,
        retry_count: int,
        task_id: str | None = None,
    ) -> SyncJob:
        job.status = "retrying"
        if task_id is not None:
            job.worker_task_id = task_id
        job.retry_count = retry_count
        job.error_message = message
        job.completed_at = None
        return job

    @staticmethod
    def mark_failed(
        job: SyncJob,
        message: str,
        *,
        result: dict[str, Any] | None = None,
        dead_lettered: bool = False,
    ) -> SyncJob:
        job.status = "dead_lettered" if dead_lettered else "failed"
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = message
        if result is not None:
            job.result_json = result
        return job
