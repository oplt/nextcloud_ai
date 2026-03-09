from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.connectors.nextcloud.schemas import NextcloudWebhookEvent
from backend.db.models import Connector, Document
from backend.services.job_service import SyncJobReservation
from backend.services.nextcloud_automation_service import NextcloudAutomationService


class FakeDebounceStore:
    def __init__(self, acquire_result: bool = True) -> None:
        self.acquire_result = acquire_result
        self.calls: list[tuple[str, int]] = []

    async def acquire(self, key: str, ttl_seconds: int) -> bool:
        self.calls.append((key, ttl_seconds))
        return self.acquire_result


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.refresh_calls: list[object] = []

    async def commit(self) -> None:
        self.commit_calls += 1

    async def refresh(self, instance: object) -> None:
        self.refresh_calls.append(instance)


def build_connector(*, last_sync_at: datetime | None = None) -> Connector:
    return Connector(
        id=uuid4(),
        connector_type="nextcloud",
        display_name="Primary Nextcloud",
        base_url="https://nextcloud.example.com",
        username="service-account",
        encrypted_secret="encrypted",
        root_path="/",
        last_sync_at=last_sync_at,
    )


def build_document(connector: Connector, *, file_path: str) -> Document:
    return Document(
        id=uuid4(),
        connector_id=connector.id,
        external_id=file_path,
        file_path=file_path,
        file_name=file_path.split("/")[-1],
        allowed_user_ids=[],
        allowed_group_ids=[],
    )


@pytest.mark.asyncio
async def test_webhook_dispatch_reindexes_known_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    connector = build_connector()
    document = build_document(connector, file_path="/docs/policy.md")
    service = NextcloudAutomationService(
        session, debounce_store=FakeDebounceStore(acquire_result=True)
    )
    service.connector_repo = SimpleNamespace(
        get=_async_return(connector),
        list_active=_async_return([connector]),
        get_active_by_base_url_and_username=_async_return(None),
    )
    service.document_repo = SimpleNamespace(
        get_by_connector_and_file_path=_async_return(document)
    )
    service.job_service = SimpleNamespace(
        reserve_sync_job=_unexpected_async("reserve_sync_job should not run")
    )

    monkeypatch.setattr(
        "backend.workers.indexing_tasks.enqueue_document_reindex",
        lambda document_id: SimpleNamespace(id=f"task:{document_id}"),
    )

    result = await service.dispatch_webhook_event(
        NextcloudWebhookEvent(
            event="files.updated",
            connector_id=str(connector.id),
            path="/docs/policy.md",
        )
    )

    assert result.accepted is True
    assert result.scheduled is True
    assert result.action == "reindex"
    assert result.connector_id == str(connector.id)
    assert result.document_id == str(document.id)
    assert result.task_id == f"task:{document.id}"
    assert session.commit_calls == 0


@pytest.mark.asyncio
async def test_webhook_dispatch_enqueues_sync_for_unknown_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    connector = build_connector()
    job = SimpleNamespace(id=uuid4(), worker_task_id=None)
    service = NextcloudAutomationService(
        session, debounce_store=FakeDebounceStore(acquire_result=True)
    )
    service.connector_repo = SimpleNamespace(
        get=_async_return(connector),
        list_active=_async_return([connector]),
        get_active_by_base_url_and_username=_async_return(None),
    )
    service.document_repo = SimpleNamespace(
        get_by_connector_and_file_path=_async_return(None)
    )
    service.job_service = SimpleNamespace(
        reserve_sync_job=_async_return(SyncJobReservation(job=job, created=True))
    )

    monkeypatch.setattr(
        "backend.workers.indexing_tasks.enqueue_connector_sync_job",
        lambda job_id: SimpleNamespace(id=f"sync-task:{job_id}"),
    )

    result = await service.dispatch_webhook_event(
        NextcloudWebhookEvent(
            event="files.created",
            connector_id=str(connector.id),
            path="/docs/new-file.md",
        )
    )

    assert result.accepted is True
    assert result.scheduled is True
    assert result.action == "sync"
    assert result.job_id == str(job.id)
    assert result.task_id == f"sync-task:{job.id}"
    assert job.worker_task_id == f"sync-task:{job.id}"
    assert session.commit_calls == 1
    assert session.refresh_calls == [job]


@pytest.mark.asyncio
async def test_webhook_dispatch_skips_when_debounced() -> None:
    session = FakeSession()
    connector = build_connector()
    service = NextcloudAutomationService(
        session, debounce_store=FakeDebounceStore(acquire_result=False)
    )
    service.connector_repo = SimpleNamespace(
        get=_async_return(connector),
        list_active=_async_return([connector]),
        get_active_by_base_url_and_username=_async_return(None),
    )
    service.document_repo = SimpleNamespace(
        get_by_connector_and_file_path=_unexpected_async(
            "get_by_connector_and_file_path should not run"
        )
    )
    service.job_service = SimpleNamespace(
        reserve_sync_job=_unexpected_async("reserve_sync_job should not run")
    )

    result = await service.dispatch_webhook_event(
        NextcloudWebhookEvent(
            event="files.updated",
            connector_id=str(connector.id),
            path="/docs/policy.md",
        )
    )

    assert result.accepted is True
    assert result.scheduled is False
    assert result.reason == "debounced"


@pytest.mark.asyncio
async def test_fallback_sync_enqueues_only_stale_connectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    now = datetime.now(timezone.utc)
    stale_connector = build_connector(
        last_sync_at=now - timedelta(hours=2)
    )
    fresh_connector = build_connector(last_sync_at=now)
    running_connector = build_connector(
        last_sync_at=now - timedelta(hours=2)
    )
    debounce_store = FakeDebounceStore(acquire_result=True)
    service = NextcloudAutomationService(session, debounce_store=debounce_store)
    service.connector_repo = SimpleNamespace(
        list_active=_async_return([stale_connector, fresh_connector, running_connector])
    )
    service.sync_job_repo = SimpleNamespace(
        get_latest_for_connector=_async_router(
            {
                stale_connector.id: None,
                fresh_connector.id: None,
                running_connector.id: SimpleNamespace(status="running"),
            }
        )
    )

    created_job = SimpleNamespace(id=uuid4(), worker_task_id=None)

    async def reserve_sync_job(**kwargs):
        assert kwargs["connector_id"] == str(stale_connector.id)
        return SyncJobReservation(job=created_job, created=True)

    service.job_service = SimpleNamespace(reserve_sync_job=reserve_sync_job)

    monkeypatch.setattr(
        "backend.workers.indexing_tasks.enqueue_connector_sync_job",
        lambda job_id: SimpleNamespace(id=f"fallback-task:{job_id}"),
    )

    summary = await service.enqueue_stale_connector_syncs(now=now)

    assert summary.scanned == 3
    assert summary.enqueued == 1
    assert summary.skipped_not_stale == 1
    assert summary.skipped_inflight == 1
    assert created_job.worker_task_id == f"fallback-task:{created_job.id}"
    assert session.commit_calls == 1
    assert session.refresh_calls == [created_job]
    assert len(debounce_store.calls) == 1


def _async_return(value):
    async def inner(*args, **kwargs):
        return value

    return inner


def _async_router(mapping):
    async def inner(connector_id):
        return mapping[connector_id]

    return inner


def _unexpected_async(message: str):
    async def inner(*args, **kwargs):
        raise AssertionError(message)

    return inner
