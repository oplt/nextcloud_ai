from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.db.repo.intelligence import KnowledgeGraphRepository
from backend.services.product_intelligence_service import ProductIntelligenceService


def test_scoped_graph_external_key_includes_connector() -> None:
    connector_id = uuid4()
    key = ProductIntelligenceService._scoped_graph_external_key(
        connector_id, "person", "Alice Example"
    )
    assert str(connector_id) in key
    assert key.startswith(f"{connector_id}:person:")


def test_scoped_graph_keys_differ_across_connectors_for_same_label() -> None:
    c1, c2 = uuid4(), uuid4()
    k1 = ProductIntelligenceService._scoped_graph_external_key(c1, "person", "Jane Doe")
    k2 = ProductIntelligenceService._scoped_graph_external_key(c2, "person", "Jane Doe")
    assert k1 != k2


@pytest.mark.asyncio
async def test_list_related_document_ids_stops_when_seed_has_no_connector() -> None:
    class Sess:
        async def execute(self, _stmt):
            r = MagicMock()
            r.all.return_value = []
            return r

    repo = KnowledgeGraphRepository(session=Sess())
    out = await repo.list_related_document_ids(document_ids=[uuid4()])
    assert out == []


@pytest.mark.asyncio
async def test_list_related_document_ids_runs_connector_scoped_related_query() -> None:
    calls: list[int] = []

    class Sess:
        async def execute(self, _stmt):
            calls.append(1)
            r = MagicMock()
            if len(calls) == 1:
                r.all.return_value = [(uuid4(),)]
            elif len(calls) == 2:
                r.all.return_value = [(uuid4(),)]
            else:
                r.all.return_value = [(uuid4(), 1)]
            return r

    repo = KnowledgeGraphRepository(session=Sess())
    out = await repo.list_related_document_ids(document_ids=[uuid4()])
    assert len(calls) == 3
    assert len(out) == 1


@pytest.mark.asyncio
async def test_list_related_document_ids_asyncmock_session() -> None:
    session = AsyncMock()
    r1, r2, r3 = MagicMock(), MagicMock(), MagicMock()
    r1.all.return_value = [(uuid4(),)]
    r2.all.return_value = [(uuid4(),)]
    r3.all.return_value = []
    session.execute.side_effect = [r1, r2, r3]

    repo = KnowledgeGraphRepository(session=session)
    out = await repo.list_related_document_ids(document_ids=[uuid4(), uuid4()])
    assert out == []
    assert session.execute.await_count == 3
