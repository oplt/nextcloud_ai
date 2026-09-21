"""Phase 2: indexing consistency — metadata, duplicates, leases, outbox, worker loop."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.ingestion.index_versions import (
    IndexAttempt,
    StaleIndexGenerationError,
    assert_publish_allowed,
    begin_index_attempt,
    mark_published,
)
from backend.services.job_lifecycle import JobLifecycleService
from backend.services.nextcloud_sync_service import NextcloudConnectorSyncService
from backend.workers.indexing_tasks import _run_in_worker_loop


@pytest.mark.asyncio
async def test_upsert_preserves_parser_metadata_and_does_not_use_etag_as_checksum() -> None:
    service = object.__new__(NextcloudConnectorSyncService)
    document = SimpleNamespace(
        file_path="",
        file_name="",
        mime_type=None,
        checksum="old-content-sha",
        size_bytes=1,
        version_tag="etag-old",
        source_url=None,
        modified_at=None,
        sync_status="synced",
        sync_error=None,
        last_seen_at=None,
        is_deleted=False,
        owner_external_id=None,
        allowed_user_ids=[],
        allowed_group_ids=[],
        public_link_enabled=False,
        acl_json=None,
        metadata_json={
            "parser": "pdfplumber",
            "indexed_content_checksum": "old-content-sha",
            "ingestion_quality": {"chunk_count": 3},
            "href": "/old",
        },
    )
    connector = SimpleNamespace(base_url="https://nc.example", id=uuid4())
    item = SimpleNamespace(
        node=SimpleNamespace(
            path="/docs/a.pdf",
            content_type="application/pdf",
            etag="etag-new",
            size_bytes=99,
            last_modified=datetime.now(timezone.utc),
            href="/remote.php/dav/files/a.pdf",
            file_id="fid-1",
        ),
        acl=SimpleNamespace(
            owner_user_id="u1",
            allowed_user_ids=["u1"],
            allowed_group_ids=[],
            public_link_enabled=False,
            model_dump=lambda mode="json": {"owner": "u1"},
        ),
    )

    class Repo:
        async def get_by_connector_and_external_id(self, *_a, **_k):
            return document

        async def add(self, *_a, **_k):
            return None

    updated, previous = await NextcloudConnectorSyncService._upsert_document(
        service,
        connector=connector,
        document_repo=Repo(),
        item=item,
    )
    assert previous == "etag-old"
    assert updated.checksum == "old-content-sha"
    assert updated.version_tag == "etag-new"
    assert updated.metadata_json["parser"] == "pdfplumber"
    assert updated.metadata_json["ingestion_quality"]["chunk_count"] == 3
    assert updated.metadata_json["href"] == "/remote.php/dav/files/a.pdf"
    assert updated.metadata_json["etag"] == "etag-new"
    assert updated.metadata_json["indexed_content_checksum"] == "old-content-sha"


def test_stale_index_generation_rejected() -> None:
    document = SimpleNamespace(id=uuid4(), index_generation=2, published_generation=1)
    attempt = IndexAttempt(document_id=str(document.id), generation=1)
    with pytest.raises(StaleIndexGenerationError):
        assert_publish_allowed(document, attempt)


@pytest.mark.asyncio
async def test_begin_index_attempt_bumps_generation() -> None:
    class Session:
        async def flush(self):
            return None

    document = SimpleNamespace(id=uuid4(), index_generation=3, published_generation=3)
    attempt = await begin_index_attempt(Session(), document)  # type: ignore[arg-type]
    assert attempt.generation == 4
    assert document.index_generation == 4
    mark_published(document, attempt)
    assert document.published_generation == 4


def test_job_lease_heartbeat_extends_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.services.job_lifecycle.settings.SYNC_JOB_LEASE_SECONDS", 60
    )
    job = SimpleNamespace(
        status="queued",
        worker_task_id=None,
        retry_count=0,
        started_at=None,
        completed_at=None,
        error_message=None,
        progress_total=None,
        progress_completed=None,
        lease_owner=None,
        lease_expires_at=None,
        last_heartbeat_at=None,
        result_json=None,
    )
    JobLifecycleService.mark_running(job, task_id="task-1")
    assert job.status == "running"
    assert job.lease_owner == "task-1"
    assert job.lease_expires_at is not None
    first_expiry = job.lease_expires_at
    JobLifecycleService.advance(job, 1)
    assert job.progress_completed == 1
    assert job.lease_expires_at >= first_expiry


def test_run_in_worker_loop_preserves_business_runtime_error() -> None:
    async def boom():
        raise RuntimeError("business failure: embedding dimension mismatch")

    with pytest.raises(RuntimeError, match="business failure"):
        _run_in_worker_loop(boom())


def test_run_in_worker_loop_does_not_rerun_exhausted_coro_on_loop_death(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    class DeadLoop:
        def is_closed(self):
            return False

        def close(self):
            return None

        def run_until_complete(self, coro):
            calls["n"] += 1
            # Exhaust the coroutine then pretend the loop died.
            try:
                coro.close()
            except Exception:
                pass
            raise RuntimeError("Event loop is closed")

    monkeypatch.setattr(
        "backend.workers.indexing_tasks._get_or_create_event_loop",
        lambda: DeadLoop(),
    )

    async def work():
        return 1

    with pytest.raises(RuntimeError, match="Event loop is closed"):
        _run_in_worker_loop(work())
    assert calls["n"] == 1


def test_outbox_idempotency_key_format() -> None:
    from backend.workers.outbox_dispatcher import TOPIC_DOCUMENT_INTELLIGENCE

    assert TOPIC_DOCUMENT_INTELLIGENCE == "document_intelligence"
    doc_id = uuid4()
    key = f"document_intelligence:{doc_id}:abc123"
    assert key.startswith("document_intelligence:")
