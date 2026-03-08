from __future__ import annotations

import asyncio

import pytest

from backend.workers import indexing_tasks


@pytest.mark.asyncio
async def test_enqueue_connector_sync_job_schedules_background_task_in_eager_mode(
    monkeypatch,
) -> None:
    event = asyncio.Event()
    calls: list[tuple[str, str | None]] = []

    async def fake_run_connector_sync_job(*, job_id: str, task_id: str | None) -> dict[str, int]:
        calls.append((job_id, task_id))
        event.set()
        return {"indexed": 1}

    monkeypatch.setattr(
        indexing_tasks, "_run_connector_sync_job", fake_run_connector_sync_job
    )
    monkeypatch.setattr(indexing_tasks.celery_app.conf, "task_always_eager", True)

    handle = indexing_tasks.enqueue_connector_sync_job("job-123")

    await asyncio.wait_for(event.wait(), timeout=1)

    assert handle.id
    assert calls == [("job-123", handle.id)]


@pytest.mark.asyncio
async def test_enqueue_document_reindex_schedules_background_task_in_eager_mode(
    monkeypatch,
) -> None:
    event = asyncio.Event()
    calls: list[str] = []

    async def fake_run_document_reindex_task(*, document_id: str) -> str:
        calls.append(document_id)
        event.set()
        return document_id

    monkeypatch.setattr(
        indexing_tasks, "_run_document_reindex_task", fake_run_document_reindex_task
    )
    monkeypatch.setattr(indexing_tasks.celery_app.conf, "task_always_eager", True)

    handle = indexing_tasks.enqueue_document_reindex("doc-123")

    await asyncio.wait_for(event.wait(), timeout=1)

    assert handle.id
    assert calls == ["doc-123"]
