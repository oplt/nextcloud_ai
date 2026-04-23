from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.db.models import Document
from backend.parsers.document_parser import ParsedDocument, ParsedPage
from backend.services.product_intelligence_service import ProductIntelligenceService


class StubInsightRepo:
    def __init__(self) -> None:
        self.items = []

    async def replace_for_document(self, document_id, insights):
        for insight in insights:
            if insight.id is None:
                insight.id = uuid4()
        self.items = list(insights)


class StubTaskRepo:
    def __init__(self) -> None:
        self.items = []

    async def replace_for_document(self, document_id, tasks):
        for task in tasks:
            if task.id is None:
                task.id = uuid4()
        self.items = list(tasks)


class StubGraphRepo:
    def __init__(self) -> None:
        self.nodes = []
        self.edges = []

    async def replace_document_graph(self, **kwargs):
        self.nodes = list(kwargs["nodes"])
        self.edges = list(kwargs["edges"])


@pytest.mark.asyncio
async def test_product_intelligence_extracts_meeting_actions_and_graph_nodes() -> None:
    document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-1",
        file_path="/meetings/weekly-sync.txt",
        file_name="weekly-sync.txt",
        allowed_user_ids=[],
        allowed_group_ids=[],
        metadata_json={"thread_key": "team-sync"},
    )
    parsed = ParsedDocument(
        text=(
            "Weekly team meeting. Decision: Ship the pilot this week. "
            "Action item: Alice Example to send rollout plan by 2026-05-01."
        ),
        pages=[
            ParsedPage(
                page_number=None,
                text=(
                    "Weekly team meeting. Decision: Ship the pilot this week. "
                    "Action item: Alice Example to send rollout plan by 2026-05-01."
                ),
            )
        ],
        metadata={"parser": "plain-text"},
    )

    service = ProductIntelligenceService(session=SimpleNamespace(flush=_noop))
    service.insight_repo = StubInsightRepo()
    service.task_repo = StubTaskRepo()
    service.graph_repo = StubGraphRepo()

    await service.rebuild_document_intelligence(document=document, parsed_document=parsed)

    insight_types = {insight.insight_type for insight in service.insight_repo.items}
    task_types = {task.task_type for task in service.task_repo.items}
    node_types = {node.node_type for node in service.graph_repo.nodes}

    assert "classification" in insight_types
    assert "meeting_summary" in insight_types
    assert "meeting_action_item" in task_types
    assert "triage_review" in task_types
    assert "thread" in node_types
    assert "person" in node_types
    meeting_insight = next(i for i in service.insight_repo.items if i.insight_type == "meeting_summary")
    prov = (meeting_insight.payload_json or {}).get("provenance") or {}
    assert prov.get("evidence_tier") == "heuristic_parse"
    person_nodes = [n for n in service.graph_repo.nodes if n.node_type == "person"]
    assert person_nodes
    assert str(document.connector_id) in person_nodes[0].external_key


@pytest.mark.asyncio
async def test_product_intelligence_extracts_contract_and_compliance_tasks() -> None:
    document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="doc-2",
        file_path="/contracts/vendor-agreement.txt",
        file_name="vendor-agreement.txt",
        allowed_user_ids=[],
        allowed_group_ids=[],
    )
    parsed = ParsedDocument(
        text=(
            "This agreement is between Acme Ltd and Example Corp. "
            "The supplier shall deliver the migration plan by 2026-06-30. "
            "The term auto-renews every year. Vendor management and backup procedures are not defined."
        ),
        pages=[],
        metadata={"parser": "plain-text"},
    )

    service = ProductIntelligenceService(session=SimpleNamespace(flush=_noop))
    service.insight_repo = StubInsightRepo()
    service.task_repo = StubTaskRepo()
    service.graph_repo = StubGraphRepo()

    await service.rebuild_document_intelligence(document=document, parsed_document=parsed)

    insight_types = {insight.insight_type for insight in service.insight_repo.items}
    task_types = {task.task_type for task in service.task_repo.items}

    assert "contract_summary" in insight_types
    assert "compliance_gap_report" in insight_types
    assert "contract_deadline" in task_types
    assert "contract_review" in task_types
    assert "compliance_gap" in task_types
    comp = next(i for i in service.insight_repo.items if i.insight_type == "compliance_gap_report")
    assert (comp.payload_json or {}).get("provenance", {}).get("evidence_tier") == "suggestion"
    gap_tasks = [t for t in service.task_repo.items if t.task_type == "compliance_gap"]
    assert gap_tasks
    assert gap_tasks[0].priority == "low"
    assert (gap_tasks[0].metadata_json or {}).get("presentation") == "suggestion"


async def _noop() -> None:
    return None
