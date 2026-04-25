from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...core.security import AuthContext
from ..models import (
    Document,
    DocumentInsight,
    KnowledgeEdge,
    KnowledgeNode,
    WorkflowTask,
)
from .base import BaseRepository
from .document import DocumentRepository


@dataclass(slots=True)
class KnowledgeNodeDraft:
    node_type: str
    external_key: str
    label: str
    metadata_json: dict | None = None
    document_id: UUID | None = None


@dataclass(slots=True)
class KnowledgeEdgeDraft:
    source_key: tuple[str, str]
    target_key: tuple[str, str]
    relation_type: str
    weight: float = 1.0
    metadata_json: dict | None = None


@dataclass(slots=True)
class WorkflowTaskWithDocument:
    task: WorkflowTask
    document: Document | None = None


class DocumentInsightRepository(BaseRepository[DocumentInsight]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DocumentInsight)

    async def delete_for_document(self, document_id: UUID | str) -> int:
        result = await self.session.execute(
            delete(DocumentInsight).where(DocumentInsight.document_id == document_id)
        )
        return int(result.rowcount or 0)

    async def replace_for_document(
        self, document_id: UUID | str, insights: Sequence[DocumentInsight]
    ) -> None:
        await self.delete_for_document(document_id)
        self.session.add_all(list(insights))
        await self.session.flush()

    async def list_by_document(self, document_id: UUID | str) -> list[DocumentInsight]:
        result = await self.session.execute(
            select(DocumentInsight)
            .where(DocumentInsight.document_id == document_id)
            .order_by(DocumentInsight.created_at.desc())
        )
        return list(result.scalars().all())


class WorkflowTaskRepository(BaseRepository[WorkflowTask]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, WorkflowTask)

    async def delete_for_document(self, document_id: UUID | str) -> int:
        result = await self.session.execute(
            delete(WorkflowTask).where(WorkflowTask.document_id == document_id)
        )
        return int(result.rowcount or 0)

    async def replace_for_document(
        self, document_id: UUID | str, tasks: Sequence[WorkflowTask]
    ) -> None:
        await self.delete_for_document(document_id)
        self.session.add_all(list(tasks))
        await self.session.flush()

    async def list_by_document(self, document_id: UUID | str) -> list[WorkflowTask]:
        result = await self.session.execute(
            select(WorkflowTask)
            .where(WorkflowTask.document_id == document_id)
            .order_by(WorkflowTask.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_open_with_documents(self, *, limit: int = 50) -> list[WorkflowTaskWithDocument]:
        result = await self.session.execute(
            select(WorkflowTask, Document)
            .outerjoin(Document, Document.id == WorkflowTask.document_id)
            .options(
                selectinload(WorkflowTask.document),
                selectinload(WorkflowTask.insight),
            )
            .where(WorkflowTask.status.in_(["queued", "in_progress", "blocked"]))
            .order_by(
                desc(WorkflowTask.priority == "high"),
                WorkflowTask.due_at.asc().nulls_last(),
                WorkflowTask.created_at.desc(),
            )
            .limit(limit)
        )
        return [
            WorkflowTaskWithDocument(task=row[0], document=row[1])
            for row in result.all()
        ]

    async def list_open_with_documents_visible_to_auth(
        self, *, auth: AuthContext, limit: int = 50
    ) -> list[WorkflowTaskWithDocument]:
        visibility = DocumentRepository.visibility_clause(auth)
        result = await self.session.execute(
            select(WorkflowTask, Document)
            .join(Document, Document.id == WorkflowTask.document_id)
            .options(
                selectinload(WorkflowTask.document),
                selectinload(WorkflowTask.insight),
            )
            .where(
                WorkflowTask.status.in_(["queued", "in_progress", "blocked"]),
                visibility,
            )
            .order_by(
                desc(WorkflowTask.priority == "high"),
                WorkflowTask.due_at.asc().nulls_last(),
                WorkflowTask.created_at.desc(),
            )
            .limit(limit)
        )
        return [
            WorkflowTaskWithDocument(task=row[0], document=row[1])
            for row in result.all()
        ]

    async def count_open_by_queue(self) -> dict[str, int]:
        result = await self.session.execute(
            select(WorkflowTask.queue_name, func.count())
            .where(WorkflowTask.status.in_(["queued", "in_progress", "blocked"]))
            .group_by(WorkflowTask.queue_name)
        )
        return {str(queue_name): int(count) for queue_name, count in result.all()}

    async def count_by_status(self) -> dict[str, int]:
        result = await self.session.execute(
            select(WorkflowTask.status, func.count()).group_by(WorkflowTask.status)
        )
        return {str(status): int(count) for status, count in result.all()}


class KnowledgeGraphRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def replace_document_graph(
        self,
        *,
        document_id: UUID | str,
        document_label: str,
        document_metadata: dict | None,
        nodes: Sequence[KnowledgeNodeDraft],
        edges: Sequence[KnowledgeEdgeDraft],
    ) -> None:
        await self.session.execute(
            delete(KnowledgeEdge).where(KnowledgeEdge.document_id == document_id)
        )
        await self.session.execute(
            delete(KnowledgeNode).where(KnowledgeNode.document_id == document_id)
        )

        resolved: dict[tuple[str, str], KnowledgeNode] = {}
        document_node = await self._get_or_create_node(
            node_type="document",
            external_key=str(document_id),
            label=document_label,
            metadata_json=document_metadata,
            document_id=document_id,
        )
        resolved[("document", str(document_id))] = document_node

        for draft in nodes:
            resolved[(draft.node_type, draft.external_key)] = await self._get_or_create_node(
                node_type=draft.node_type,
                external_key=draft.external_key,
                label=draft.label,
                metadata_json=draft.metadata_json,
                document_id=draft.document_id,
            )

        graph_edges = []
        for draft in edges:
            source_node = resolved.get(draft.source_key)
            target_node = resolved.get(draft.target_key)
            if source_node is None or target_node is None:
                continue
            graph_edges.append(
                KnowledgeEdge(
                    source_node_id=source_node.id,
                    target_node_id=target_node.id,
                    document_id=document_id,
                    relation_type=draft.relation_type,
                    weight=draft.weight,
                    metadata_json=draft.metadata_json,
                )
            )

        self.session.add_all(graph_edges)
        await self.session.flush()

    async def list_graph_for_document(
        self, document_id: UUID | str
    ) -> tuple[list[KnowledgeNode], list[KnowledgeEdge]]:
        edge_result = await self.session.execute(
            select(KnowledgeEdge)
            .where(KnowledgeEdge.document_id == document_id)
            .order_by(KnowledgeEdge.relation_type.asc(), KnowledgeEdge.created_at.asc())
        )
        edges = list(edge_result.scalars().all())
        if not edges:
            return [], []

        node_ids = {
            *[edge.source_node_id for edge in edges],
            *[edge.target_node_id for edge in edges],
        }
        node_result = await self.session.execute(
            select(KnowledgeNode)
            .where(KnowledgeNode.id.in_(list(node_ids)))
            .order_by(KnowledgeNode.node_type.asc(), KnowledgeNode.label.asc())
        )
        return list(node_result.scalars().all()), edges

    async def list_related_document_ids(
        self,
        *,
        document_ids: Sequence[UUID],
        limit: int = 6,
    ) -> list[UUID]:
        if not document_ids:
            return []

        seed_ids = list(document_ids)
        seed_conn_result = await self.session.execute(
            select(Document.connector_id)
            .where(Document.id.in_(seed_ids))
            .distinct()
        )
        seed_connector_ids = [
            row[0] for row in seed_conn_result.all() if row[0] is not None
        ]
        if not seed_connector_ids:
            return []

        entity_result = await self.session.execute(
            select(KnowledgeEdge.target_node_id)
            .where(KnowledgeEdge.document_id.in_(seed_ids))
        )
        entity_node_ids = [row[0] for row in entity_result.all() if row[0] is not None]
        if not entity_node_ids:
            return []

        related_result = await self.session.execute(
            select(KnowledgeEdge.document_id, func.count().label("hits"))
            .join(Document, Document.id == KnowledgeEdge.document_id)
            .where(
                KnowledgeEdge.target_node_id.in_(entity_node_ids),
                KnowledgeEdge.document_id.is_not(None),
                KnowledgeEdge.document_id.not_in(seed_ids),
                Document.connector_id.in_(seed_connector_ids),
            )
            .group_by(KnowledgeEdge.document_id)
            .order_by(desc("hits"))
            .limit(limit)
        )
        return [row[0] for row in related_result.all() if row[0] is not None]

    async def delete_for_document(self, document_id: UUID | str) -> None:
        await self.session.execute(
            delete(KnowledgeEdge).where(KnowledgeEdge.document_id == document_id)
        )
        await self.session.execute(
            delete(KnowledgeNode).where(KnowledgeNode.document_id == document_id)
        )
        await self.session.flush()

    async def _get_or_create_node(
        self,
        *,
        node_type: str,
        external_key: str,
        label: str,
        metadata_json: dict | None = None,
        document_id: UUID | str | None = None,
    ) -> KnowledgeNode:
        result = await self.session.execute(
            select(KnowledgeNode).where(
                KnowledgeNode.node_type == node_type,
                KnowledgeNode.external_key == external_key,
            )
        )
        node = result.scalar_one_or_none()
        if node is None:
            node = KnowledgeNode(
                node_type=node_type,
                external_key=external_key,
                label=label,
                metadata_json=metadata_json,
                document_id=document_id,
            )
            self.session.add(node)
            await self.session.flush()
            return node

        node.label = label
        if metadata_json:
            node.metadata_json = {**dict(node.metadata_json or {}), **metadata_json}
        if document_id is not None:
            node.document_id = document_id
        await self.session.flush()
        return node
