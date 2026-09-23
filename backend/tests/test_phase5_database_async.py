"""Phase 5 database/async contracts: lazy raise, chat list, celery, parse pool, sync queue."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.db.models import ChatSession, Connector, Document, Role, User
from backend.parsers import document_parser
from backend.services.bounded_work import map_bounded
from backend.workers import indexing_tasks


def test_document_chunks_lazy_raise() -> None:
    from sqlalchemy.orm import class_mapper

    rel = class_mapper(Document).relationships["chunks"]
    assert rel.lazy == "raise"

    chat_rel = class_mapper(ChatSession).relationships["messages"]
    assert chat_rel.lazy == "raise"

    for model, names in (
        (Role, ("users",)),
        (User, ("chat_sessions", "audit_logs", "requested_jobs", "owned_connectors")),
        (Connector, ("documents", "sync_jobs")),
    ):
        for name in names:
            assert class_mapper(model).relationships[name].lazy == "raise"


def test_chat_session_subject_without_messages_loaded() -> None:
    session = ChatSession(user_id=uuid4(), title="Fallback title")
    session._subject_preview = "preview from subquery"  # type: ignore[attr-defined]
    assert session.subject == "preview from subquery"

    bare = ChatSession(user_id=uuid4(), title="Only title")
    # messages relationship is lazy=raise — subject must not crash.
    assert bare.subject == "Only title"
    assert bare.active_context_document_ids == []


def test_celery_local_mode_never_skips_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import settings

    monkeypatch.setattr(settings, "CELERY_LOCAL_MODE", "never")
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(indexing_tasks.celery_app.conf, "task_always_eager", False)

    ping = MagicMock()
    monkeypatch.setattr(indexing_tasks, "_celery_worker_is_available", ping)
    assert indexing_tasks.should_execute_tasks_locally() is False
    ping.assert_not_called()


def test_celery_local_mode_auto_skips_ping_outside_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.core.config import settings

    monkeypatch.setattr(settings, "CELERY_LOCAL_MODE", "auto")
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(indexing_tasks.celery_app.conf, "task_always_eager", False)

    ping = MagicMock(return_value=False)
    monkeypatch.setattr(indexing_tasks, "_celery_worker_is_available", ping)
    assert indexing_tasks.should_execute_tasks_locally() is False
    ping.assert_not_called()


@pytest.mark.asyncio
async def test_parse_document_bytes_uses_bounded_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    class FakeLoop:
        async def run_in_executor(self, executor, fn, *args):
            calls.append(executor)
            assert isinstance(executor, ThreadPoolExecutor)
            return fn(*args)

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: FakeLoop())
    parsed = await document_parser.parse_document_bytes(
        "note.txt",
        "text/plain",
        b"hello world",
    )
    assert "hello world" in parsed.text
    assert len(calls) == 1
    assert document_parser._PARSE_EXECUTOR is calls[0]


@pytest.mark.asyncio
async def test_sync_queue_worker_count_bounded() -> None:
    """The production helper uses fixed workers and a backpressured queue."""
    concurrency = 3
    items = list(range(11))
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def handler(item: int) -> int:
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.001)
        async with lock:
            active -= 1
        return item

    seen = await map_bounded(items, handler, concurrency=concurrency)
    assert sorted(seen) == items
    assert max_active == concurrency


@pytest.mark.asyncio
async def test_semantic_search_sets_probes_on_broad_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.core.config import settings
    from backend.core.security import AuthContext
    from backend.db.repo.document import DocumentChunkRepository

    monkeypatch.setattr(settings, "PGVECTOR_IVFFLAT_PROBES", 17)
    monkeypatch.setattr(settings, "PGVECTOR_EXACT_SEARCH_MAX_CANDIDATES", 2000)

    session = AsyncMock()
    executed: list[str] = []

    async def _execute(stmt, *args, **kwargs):
        executed.append(str(stmt))
        result = MagicMock()
        result.all = MagicMock(return_value=[])
        return result

    session.execute = _execute
    repo = DocumentChunkRepository(session)
    auth = AuthContext(user_id=str(uuid4()), auth_provider="local", is_superuser=True)
    await repo.semantic_search(
        embedding=[0.0] * 8,
        auth=auth,
        limit=4,
        document_ids=None,
    )
    assert any("ivfflat.probes" in s and "17" in s for s in executed)


@pytest.mark.asyncio
async def test_semantic_search_skips_probes_when_selective(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.core.config import settings
    from backend.core.security import AuthContext
    from backend.db.repo.document import DocumentChunkRepository

    monkeypatch.setattr(settings, "PGVECTOR_IVFFLAT_PROBES", 17)
    monkeypatch.setattr(settings, "PGVECTOR_EXACT_SEARCH_MAX_CANDIDATES", 2000)

    session = AsyncMock()
    executed: list[str] = []

    async def _execute(stmt, *args, **kwargs):
        executed.append(str(stmt))
        result = MagicMock()
        result.all = MagicMock(return_value=[])
        return result

    session.execute = _execute
    repo = DocumentChunkRepository(session)
    auth = AuthContext(user_id=str(uuid4()), auth_provider="local", is_superuser=True)
    await repo.semantic_search(
        embedding=[0.0] * 8,
        auth=auth,
        limit=4,
        document_ids=[uuid4() for _ in range(3)],
    )
    assert not any("ivfflat.probes" in s for s in executed)
    assert any(" + 0.0" in s for s in executed)


@pytest.mark.asyncio
async def test_authorized_chunk_expansion_batches_documents() -> None:
    from sqlalchemy.dialects import postgresql

    from backend.core.security import AuthContext
    from backend.db.repo.chunk_expansion import AuthorizedChunkExpansionRepository

    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result
    document_ids = [uuid4(), uuid4(), uuid4()]
    auth = AuthContext(user_id=str(uuid4()), auth_provider="local", is_superuser=True)

    grouped = await AuthorizedChunkExpansionRepository(session).list_grouped(
        document_ids=document_ids,
        auth=auth,
    )

    session.execute.assert_awaited_once()
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "row_number() OVER (PARTITION BY" in sql
    assert "document_row_number" in sql
    assert "documents.is_deleted IS false" in sql
    assert grouped == {str(document_id): [] for document_id in document_ids}


def test_document_detail_prefers_sql_chunk_count() -> None:
    from datetime import datetime, timezone

    from backend.api.v1.document_routes import _document_detail
    from backend.schemas.document_schema import DocumentDetail

    now = datetime.now(timezone.utc)
    detail = DocumentDetail.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000099",
            "created_at": now,
            "updated_at": now,
            "file_name": "a.txt",
            "file_path": "/a.txt",
            "source_type": "upload",
            "sync_status": "synced",
            "parse_status": "indexed",
            "is_deleted": False,
            "allowed_user_ids": [],
            "allowed_group_ids": [],
            "public_link_enabled": False,
            "chunks": [],
            "insights": [],
            "workflow_tasks": [],
            "knowledge_nodes": [],
            "knowledge_edges": [],
            "metadata_json": {},
        }
    )
    out = _document_detail(detail, chunk_count=42)
    assert out.chunk_count == 42
