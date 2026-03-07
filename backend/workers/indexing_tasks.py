from __future__ import annotations

import asyncio
from backend.db.session import AsyncSessionLocal
from backend.services.indexing_service import DocumentIngestionService
from backend.services.job_lifecycle import JobLifecycleService
from backend.services.nextcloud_sync_service import NextcloudConnectorSyncService
from backend.workers.celery_app import celery_app


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=3)
def run_connector_sync_job(self, job_id: str) -> dict[str, int]:
    return asyncio.run(_run_connector_sync_job(job_id=job_id, task_id=self.request.id))


async def _run_connector_sync_job(*, job_id: str, task_id: str | None) -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        from backend.db.repo.sync_job import SyncJobRepository

        job_repo = SyncJobRepository(session)
        job = await job_repo.get(job_id)
        if job is None:
            raise ValueError(f"Sync job {job_id} not found")
        JobLifecycleService.mark_running(job, task_id=task_id)
        await session.commit()

        service = NextcloudConnectorSyncService(session)
        connector = await service.connector_repo.get(job.connector_id)
        if connector is None:
            raise ValueError(f"Connector {job.connector_id} not found")
        result = await service.sync_connector(
            connector,
            full_reindex=bool((job.payload_json or {}).get("full_reindex", False)),
            job=job,
        )
        return result


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=3)
def run_document_reindex_task(self, document_id: str) -> str:
    return asyncio.run(_run_document_reindex_task(document_id=document_id))


async def _run_document_reindex_task(*, document_id: str) -> str:
    async with AsyncSessionLocal() as session:
        service = DocumentIngestionService(session)
        document = await service.index_document(document_id)
        await session.commit()
        return str(document.id)


def enqueue_connector_sync_job(job_id: str):
    return run_connector_sync_job.delay(job_id)



def enqueue_document_reindex(document_id: str):
    return run_document_reindex_task.delay(document_id)
