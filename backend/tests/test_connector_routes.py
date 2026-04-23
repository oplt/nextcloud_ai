from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.api.v1 import connector_routes
from backend.db.models import SyncJob
from backend.schemas.connector_schema import ConnectorSyncRequest


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.refresh_calls: list[object] = []

    async def commit(self) -> None:
        self.commit_calls += 1

    async def refresh(self, instance: object) -> None:
        self.refresh_calls.append(instance)


@pytest.mark.asyncio
async def test_sync_connector_reuses_active_job(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    existing_job = SyncJob(
        id=uuid4(),
        connector_id=uuid4(),
        job_key="sync:existing",
        job_type="sync",
        status="running",
        retry_count=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    create_calls: list[dict[str, object]] = []

    class FakeJobService:
        def __init__(self, _session: object) -> None:
            self.repo = SimpleNamespace(
                get_latest_for_connector=_async_return(existing_job)
            )

        async def create_sync_job(self, **kwargs):
            create_calls.append(kwargs)
            return existing_job

    class FakeConnectorService:
        def __init__(self, _session: object) -> None:
            pass

        async def get_connector_for_actor(self, *_args, **_kwargs):
            return SimpleNamespace(id=existing_job.connector_id)

    monkeypatch.setattr(connector_routes, "JobService", FakeJobService)
    monkeypatch.setattr(connector_routes, "ConnectorService", FakeConnectorService)
    monkeypatch.setattr(connector_routes, "should_execute_tasks_locally", lambda: False)
    monkeypatch.setattr(
        connector_routes,
        "enqueue_connector_sync_job",
        lambda _job_id: (_ for _ in ()).throw(AssertionError("enqueue should not run")),
    )

    response = await connector_routes.sync_connector(
        connector_id=str(existing_job.connector_id),
        payload=ConnectorSyncRequest(full_reindex=False),
        session=session,
        identity=SimpleNamespace(user=SimpleNamespace(id=uuid4())),
    )

    assert response.id == existing_job.id
    assert create_calls == []
    assert session.commit_calls == 0
    assert session.refresh_calls == []


@pytest.mark.asyncio
async def test_sync_connector_executes_existing_queued_job_locally_when_no_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    existing_job = SyncJob(
        id=uuid4(),
        connector_id=uuid4(),
        job_key="sync:queued",
        job_type="sync",
        status="queued",
        retry_count=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    create_calls: list[dict[str, object]] = []

    class FakeJobService:
        def __init__(self, _session: object) -> None:
            self.repo = SimpleNamespace(
                get_latest_for_connector=_async_return(existing_job)
            )

        async def create_sync_job(self, **kwargs):
            create_calls.append(kwargs)
            return existing_job

    class FakeConnectorService:
        def __init__(self, _session: object) -> None:
            pass

        async def get_connector_for_actor(self, *_args, **_kwargs):
            return SimpleNamespace(id=existing_job.connector_id)

    monkeypatch.setattr(connector_routes, "JobService", FakeJobService)
    monkeypatch.setattr(connector_routes, "ConnectorService", FakeConnectorService)
    monkeypatch.setattr(connector_routes, "should_execute_tasks_locally", lambda: True)
    monkeypatch.setattr(
        connector_routes,
        "enqueue_connector_sync_job",
        lambda _job_id: SimpleNamespace(id="local-task-123"),
    )

    response = await connector_routes.sync_connector(
        connector_id=str(existing_job.connector_id),
        payload=ConnectorSyncRequest(full_reindex=False),
        session=session,
        identity=SimpleNamespace(user=SimpleNamespace(id=uuid4())),
    )

    assert response.id == existing_job.id
    assert response.worker_task_id == "local-task-123"
    assert create_calls == []
    assert session.commit_calls == 1
    assert session.refresh_calls == [existing_job]


def _async_return(value):
    async def inner(*args, **kwargs):
        return value

    return inner
