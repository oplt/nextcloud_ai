from __future__ import annotations

from uuid import uuid4

from backend.db.models import SyncJob
from backend.services.job_lifecycle import JobLifecycleService


def test_job_lifecycle_transitions() -> None:
    job = SyncJob(
        id=uuid4(),
        connector_id=uuid4(),
        job_key="sync:test",
    )

    JobLifecycleService.mark_running(job, task_id="celery-123", total=5)
    JobLifecycleService.advance(job, 3)
    JobLifecycleService.mark_succeeded(job, {"indexed": 3})

    assert job.status == "succeeded"
    assert job.worker_task_id == "celery-123"
    assert job.progress_total == 5
    assert job.progress_completed == 3
    assert job.result_json == {"indexed": 3}
    assert job.started_at is not None
    assert job.completed_at is not None
