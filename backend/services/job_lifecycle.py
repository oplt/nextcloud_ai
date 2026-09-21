from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..core.config import settings
from ..db.models import SyncJob


class JobLifecycleService:
    @staticmethod
    def _lease_ttl_seconds() -> int:
        return int(getattr(settings, "SYNC_JOB_LEASE_SECONDS", 120) or 120)

    @classmethod
    def mark_running(
        cls,
        job: SyncJob,
        *,
        task_id: str | None = None,
        total: int | None = None,
        retry_count: int | None = None,
        lease_owner: str | None = None,
    ) -> SyncJob:
        now = datetime.now(timezone.utc)
        job.status = "running"
        if task_id is not None:
            job.worker_task_id = task_id
        if retry_count is not None:
            job.retry_count = retry_count
        job.started_at = now
        job.completed_at = None
        job.error_message = None
        owner = lease_owner or task_id or job.worker_task_id or "worker"
        job.lease_owner = owner
        job.last_heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=cls._lease_ttl_seconds())
        if total is not None:
            job.progress_total = total
            job.progress_completed = 0
        return job

    @classmethod
    def heartbeat(cls, job: SyncJob, *, lease_owner: str | None = None) -> SyncJob:
        now = datetime.now(timezone.utc)
        if lease_owner is not None:
            job.lease_owner = lease_owner
        job.last_heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=cls._lease_ttl_seconds())
        return job

    @classmethod
    def advance(cls, job: SyncJob, completed: int) -> SyncJob:
        job.progress_completed = completed
        return cls.heartbeat(job)

    @staticmethod
    def mark_succeeded(job: SyncJob, result: dict[str, Any]) -> SyncJob:
        job.status = "succeeded"
        job.completed_at = datetime.now(timezone.utc)
        job.result_json = result
        job.error_message = None
        job.lease_expires_at = None
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
        job.lease_expires_at = None
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
        job.lease_expires_at = None
        if result is not None:
            job.result_json = result
        return job
