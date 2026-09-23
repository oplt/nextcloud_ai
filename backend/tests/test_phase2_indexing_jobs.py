"""Phase 2: indexing consistency — metadata, duplicates, leases, outbox, worker loop."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
from backend.ingestion.classifier import ClassificationResult
from backend.ingestion.pipeline import IngestionPipeline
from backend.parsers.document_parser import ParsedDocument, ParsedPage
from backend.services.job_lifecycle import JobLifecycleService
from backend.services.indexing_service import DocumentIngestionService
from backend.services.nextcloud_sync_service import NextcloudConnectorSyncService
from backend.services.retrieval_service import RetrievalService
from backend.workers.indexing_tasks import _run_in_worker_loop


@pytest.mark.asyncio
async def test_upsert_preserves_parser_metadata_and_does_not_use_etag_as_checksum() -> (
    None
):
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

        async def get_by_connector_and_external_id_for_update(self, *_a, **_k):
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
    class Result:
        @staticmethod
        def scalar_one_or_none():
            return 4

    class Session:
        async def flush(self):
            return None

        async def execute(self, _statement):
            return Result()

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
    key = f"document_intelligence:v1:{doc_id}:7:abc123"
    assert key.startswith("document_intelligence:v1:")


def test_failed_reindex_preserves_published_searchable_generation() -> None:
    document = SimpleNamespace(
        sync_status="synced",
        sync_error=None,
        parse_status="lexical_ready",
        parse_error="embedding provider unavailable",
        published_generation=4,
        ingestion_events_json=[],
    )

    NextcloudConnectorSyncService._mark_document_ingest_failure(
        document, "temporary database disconnect"
    )

    assert document.sync_status == "error"
    assert document.parse_status == "lexical_ready"
    assert document.parse_error == "embedding provider unavailable"
    assert document.ingestion_events_json[-1]["status"] == (
        "failed_preserving_published_index"
    )


@pytest.mark.asyncio
async def test_query_embedding_failure_falls_back_to_lexical_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenEmbeddingClient:
        async def embed_query(self, _question: str):
            raise RuntimeError("embedding service unavailable")

    service = object.__new__(RetrievalService)
    service.embedding_client = BrokenEmbeddingClient()
    service.graph_repo = SimpleNamespace()
    calls: list[list[float]] = []

    async def fake_run_retrieval(**kwargs):
        calls.append(kwargs["query_embedding"])
        return []

    monkeypatch.setattr(service, "_run_retrieval", fake_run_retrieval)
    result = await RetrievalService.retrieve(
        service,
        question="invoice 2026",
        auth=SimpleNamespace(),
    )

    assert calls == [[]]
    assert result.query_embedding == []
    assert result.retrieval_debug["query_embedding"]["available"] is False


@pytest.mark.asyncio
async def test_intelligence_outbox_key_is_generation_versioned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Outbox:
        async def enqueue(self, **kwargs):
            captured.update(kwargs)

    service = object.__new__(DocumentIngestionService)
    service.outbox = Outbox()
    monkeypatch.setattr(
        "backend.services.indexing_service.settings.PRODUCT_INTELLIGENCE_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "backend.services.indexing_service.settings.PRODUCT_INTELLIGENCE_EXTRACTION_MODE",
        "async",
    )
    document_id = uuid4()
    document = SimpleNamespace(
        id=document_id,
        checksum="new-unpublished-checksum",
        version_tag="etag",
        published_generation=8,
        metadata_json={"indexed_content_checksum": "published-checksum"},
    )

    await DocumentIngestionService._enqueue_intelligence_outbox(service, document)

    assert captured["idempotency_key"] == (
        f"document_intelligence:v1:{document_id}:8:published-checksum"
    )
    assert captured["payload"] == {
        "document_id": str(document_id),
        "published_generation": 8,
        "indexed_content_checksum": "published-checksum",
    }


@pytest.mark.asyncio
async def test_restart_cleanup_only_targets_explicitly_expired_leases() -> None:
    from backend.db.repo.sync_job import SyncJobRepository

    class Result:
        rowcount = 0

    class Session:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return Result()

        async def commit(self):
            return None

    session = Session()
    await SyncJobRepository(session).reset_stale_running_jobs(message="expired")
    sql = str(session.statement.compile(compile_kwargs={"literal_binds": True}))
    assert "lease_expires_at IS NOT NULL" in sql
    assert "lease_expires_at <" in sql
    assert "lease_expires_at IS NULL" not in sql


@pytest.mark.asyncio
async def test_stale_nextcloud_snapshot_does_not_replace_newer_metadata() -> None:
    service = object.__new__(NextcloudConnectorSyncService)
    newer_modified = datetime.now(timezone.utc)
    document = SimpleNamespace(
        version_tag="etag-new",
        modified_at=newer_modified,
        last_seen_at=None,
        metadata_json={"indexed_content_checksum": "sha-new"},
    )

    class Repo:
        async def get_by_connector_and_external_id_for_update(self, *_a, **_k):
            return document

    item = SimpleNamespace(
        node=SimpleNamespace(
            file_id="file-1",
            path="/a.pdf",
            etag="etag-old",
            last_modified=newer_modified - timedelta(minutes=1),
        )
    )
    updated, previous = await NextcloudConnectorSyncService._upsert_document(
        service,
        connector=SimpleNamespace(id=uuid4()),
        document_repo=Repo(),
        item=item,
    )

    assert updated.version_tag == "etag-new"
    assert updated.metadata_json["indexed_content_checksum"] == "sha-new"
    assert previous == "etag-old"


@pytest.mark.asyncio
async def test_duplicate_payload_replaces_target_chunks_with_target_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_id = uuid4()
    source_id = uuid4()
    target = SimpleNamespace(
        id=target_id,
        file_name="a.txt",
        mime_type="text/plain",
        source_type="nextcloud",
        checksum="hash-x",
        size_bytes=1,
        version_tag="etag-y",
        index_generation=0,
        published_generation=0,
        parse_status="indexed",
        metadata_json={"indexed_content_checksum": "hash-x", "href": "/a"},
        ingestion_events_json=[],
    )
    source = SimpleNamespace(
        id=source_id,
        parse_status="indexed",
        parse_error=None,
        indexed_at=datetime.now(timezone.utc),
        document_type="policy_document",
        document_type_confidence=0.9,
        document_type_reason="rules",
        document_type_source="rules",
        business_domain="operations",
        business_domain_confidence=0.8,
        business_domain_reason="rules",
        business_domain_source="rules",
        intelligence_json={"dates": []},
        page_count=1,
        word_count=10,
        token_count=10,
        language="en",
        metadata_json={"ingestion_quality": {"chunk_count": 1}},
    )
    source_chunk = SimpleNamespace(
        chunk_index=0,
        content="payload Y searchable content",
        token_count=4,
        char_start=0,
        char_end=28,
        page_number=1,
        section_title=None,
        heading_path=None,
        content_hash="chunk-y",
        embedding=[0.1, 0.2],
        chunk_type="text",
        embedding_status="embedded",
        embedding_model="test",
        metadata_json={"document_id": str(source_id)},
    )

    class Result:
        @staticmethod
        def scalar_one_or_none():
            return 1

    class Session:
        async def flush(self):
            return None

        async def execute(self, _statement):
            return Result()

    class DocumentRepo:
        async def find_indexed_duplicate(self, **_kwargs):
            return source

    class ChunkRepo:
        replaced = []

        async def list_by_document(self, document_id):
            assert document_id == source_id
            return [source_chunk]

        async def replace_for_document(self, document_id, chunks, **_kwargs):
            assert document_id == target_id
            self.replaced = list(chunks)

    service = object.__new__(DocumentIngestionService)
    service.session = Session()
    service.document_repo = DocumentRepo()
    service.chunk_repo = ChunkRepo()
    service.outbox = SimpleNamespace()
    monkeypatch.setattr(
        "backend.services.indexing_service.settings.PRODUCT_INTELLIGENCE_ENABLED",
        False,
    )

    await DocumentIngestionService.ingest_document_bytes(service, target, b"Y")

    assert target.checksum != "hash-x"
    assert target.metadata_json["indexed_content_checksum"] == target.checksum
    assert target.published_generation == 1
    assert service.chunk_repo.replaced[0].content == "payload Y searchable content"
    assert service.chunk_repo.replaced[0].document_id == target_id
    assert service.chunk_repo.replaced[0].metadata_json["document_id"] == str(target_id)


@pytest.mark.asyncio
async def test_embedding_failure_publishes_lexical_chunks() -> None:
    class BrokenEmbeddings:
        async def embed_documents(self, _texts):
            raise RuntimeError("provider offline")

    class Classifier:
        async def classify(self, **_kwargs):
            return ClassificationResult(
                document_type="policy_document",
                document_type_confidence=0.9,
                document_type_reason="test",
                document_type_source="rules",
                business_domain="operations",
                business_domain_confidence=0.8,
                business_domain_reason="test",
                business_domain_source="rules",
            )

    class ChunkRepo:
        replaced = []

        async def list_by_document(self, _document_id):
            return []

        async def replace_for_document(self, _document_id, chunks, **_kwargs):
            self.replaced = list(chunks)

    pipeline = object.__new__(IngestionPipeline)
    pipeline.embedding_client = BrokenEmbeddings()
    pipeline.classifier = Classifier()
    pipeline.chunk_repo = ChunkRepo()
    document = SimpleNamespace(
        id=uuid4(),
        connector_id=uuid4(),
        file_name="policy.txt",
        file_path="/policy.txt",
        file_extension=None,
        source_type="nextcloud",
        permission_scope=None,
        page_count=None,
        word_count=None,
        token_count=None,
        language=None,
        public_link_enabled=False,
        owner_external_id="user-1",
        allowed_user_ids=["user-1"],
        allowed_group_ids=[],
        parse_status="pending",
        parse_error=None,
        metadata_json={},
        ingestion_events_json=[],
    )
    parsed = ParsedDocument(
        text="This policy remains searchable even while embeddings are unavailable. "
        * 3,
        pages=[ParsedPage(page_number=1, text="policy")],
        metadata={"parser": "text"},
    )

    chunks = await IngestionPipeline.ingest_document(pipeline, document, parsed)

    assert chunks
    assert document.parse_status == "lexical_ready"
    assert document.metadata_json["ingestion_quality"]["embedding_status"] == "failed"
    assert all(chunk.embedding is None for chunk in chunks)
    assert all(chunk.content for chunk in pipeline.chunk_repo.replaced)


@pytest.mark.asyncio
async def test_short_text_reaches_partially_parsed_final_status() -> None:
    class ChunkRepo:
        replaced = None

        async def replace_for_document(self, _document_id, chunks, **_kwargs):
            self.replaced = list(chunks)

    pipeline = object.__new__(IngestionPipeline)
    pipeline.chunk_repo = ChunkRepo()
    document = SimpleNamespace(
        id=uuid4(),
        file_name="note.txt",
        file_extension=None,
        source_type="nextcloud",
        permission_scope=None,
        page_count=None,
        word_count=None,
        token_count=None,
        language=None,
        public_link_enabled=False,
        owner_external_id=None,
        allowed_user_ids=[],
        allowed_group_ids=[],
        parse_status="pending",
        parse_error=None,
        metadata_json={},
        ingestion_events_json=[],
    )
    parsed = ParsedDocument(text="brief note", pages=[], metadata={"parser": "text"})

    chunks = await IngestionPipeline.ingest_document(pipeline, document, parsed)

    assert chunks == []
    assert pipeline.chunk_repo.replaced == []
    assert document.parse_status == "partially_parsed"


@pytest.mark.asyncio
async def test_outbox_reclaims_abandoned_processing_rows() -> None:
    from backend.db.repo.outbox import WorkOutboxRepository

    class Scalars:
        @staticmethod
        def all():
            return []

    class Result:
        @staticmethod
        def scalars():
            return Scalars()

    class Session:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return Result()

    session = Session()
    rows = await WorkOutboxRepository(session).claim_batch(
        processing_timeout_seconds=60
    )
    sql = str(session.statement.compile(compile_kwargs={"literal_binds": True}))

    assert rows == []
    assert "work_outbox.status = 'processing'" in sql
    assert "work_outbox.updated_at <" in sql
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_broker_failure_after_commit_leaves_outbox_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.workers import outbox_dispatcher

    row = SimpleNamespace(
        id=uuid4(),
        topic="document_intelligence",
        payload_json={"document_id": str(uuid4()), "published_generation": 3},
    )
    retried: list[tuple[object, str]] = []

    class Session:
        def __init__(self):
            self.commits = 0

        async def commit(self):
            self.commits += 1

    source_session = Session()
    mark_session = Session()

    class SessionContext:
        async def __aenter__(self):
            return mark_session

        async def __aexit__(self, *_args):
            return None

    class Repo:
        def __init__(self, session):
            self.session = session

        async def claim_batch(self, **_kwargs):
            return [row]

        async def mark_retry(self, row_id, *, error):
            retried.append((row_id, error))

    async def broker_failure(_topic, _payload):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(outbox_dispatcher, "WorkOutboxRepository", Repo)
    monkeypatch.setattr(outbox_dispatcher, "AsyncSessionLocal", SessionContext)
    monkeypatch.setattr(outbox_dispatcher, "_dispatch_row", broker_failure)

    result = await outbox_dispatcher.dispatch_outbox_batch(source_session)

    assert source_session.commits == 1
    assert mark_session.commits == 1
    assert retried == [(row.id, "broker unavailable")]
    assert result == {"done": 0, "failed": 1, "retried": 1, "claimed": 1}


@pytest.mark.asyncio
async def test_outbox_redelivery_carries_the_published_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.workers import indexing_tasks, outbox_dispatcher

    calls: list[tuple[str, int | None]] = []

    def enqueue(document_id: str, *, expected_generation: int | None = None):
        calls.append((document_id, expected_generation))

    monkeypatch.setattr(
        indexing_tasks, "enqueue_document_intelligence_immediate", enqueue
    )
    document_id = str(uuid4())

    await outbox_dispatcher._dispatch_row(
        "document_intelligence",
        {"document_id": document_id, "published_generation": 11},
    )

    assert calls == [(document_id, 11)]


@pytest.mark.asyncio
async def test_redelivered_intelligence_generation_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.workers import indexing_tasks

    document_id = str(uuid4())
    document = SimpleNamespace(
        published_generation=5,
        metadata_json={"intelligence_published_generation": 5},
    )
    recomputed = 0

    class Repo:
        async def get_for_update(self, requested_id):
            assert requested_id == document_id
            return document

    class Service:
        def __init__(self, _session):
            self.document_repo = Repo()

        async def recompute_product_intelligence(self, _document_id):
            nonlocal recomputed
            recomputed += 1

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def commit(self):
            raise AssertionError("idempotent redelivery must not write")

        async def rollback(self):
            return None

    monkeypatch.setattr(indexing_tasks, "AsyncSessionLocal", Session)
    monkeypatch.setattr(indexing_tasks, "DocumentIngestionService", Service)
    monkeypatch.setattr(indexing_tasks.settings, "PRODUCT_INTELLIGENCE_ENABLED", True)

    result = await indexing_tasks._run_document_intelligence_extraction_task(
        document_id=document_id,
        expected_generation=5,
    )

    assert result == document_id
    assert recomputed == 0


def test_worker_process_reuses_one_resource_loop() -> None:
    from backend.workers.indexing_tasks import (
        close_worker_loop,
        initialize_worker_loop,
    )

    close_worker_loop()
    first = initialize_worker_loop()
    second = initialize_worker_loop()
    try:
        assert first is second
        assert not first.is_closed()
    finally:
        close_worker_loop()
    assert first.is_closed()
