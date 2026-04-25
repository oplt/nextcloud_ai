from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
import logging
import re
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.security import AuthContext
from ..db.models import Document, DocumentInsight, WorkflowTask
from ..db.repo.document import DocumentRepository
from ..db.repo.intelligence import (
    DocumentInsightRepository,
    KnowledgeEdgeDraft,
    KnowledgeGraphRepository,
    KnowledgeNodeDraft,
    WorkflowTaskRepository,
)
from ..parsers.document_parser import ParsedDocument
from ..schemas.document_schema import DocumentDetail
from . import intelligence_provenance as intel_prov
from ..schemas.intelligence_schema import (
    IntelligenceOpenTaskRead,
    IntelligenceOverviewRead,
    IntelligenceSpotlightDocumentRead,
)
logger = logging.getLogger(__name__)

_MEETING_HINTS = (
    "meeting",
    "minutes",
    "transcript",
    "standup",
    "retro",
    "action items",
    "attendees",
    "agenda",
)
_CONTRACT_HINTS = (
    "agreement",
    "contract",
    "statement of work",
    "sow",
    "msa",
    "master services agreement",
    "nda",
    "renewal",
    "effective date",
    "counterparty",
)
_COMPLIANCE_HINTS = (
    "iso 27001",
    "checklist",
    "policy",
    "control",
    "requirement",
    "non-compliant",
    "gap",
    "compliance",
    "standard",
)
_POLICY_HINTS = ("policy", "procedure", "standard", "handbook")

_DATE_PATTERNS = [
    "%Y-%m-%d",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
]
_DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|"
    r"(?:\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})|"
    r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}))\b",
    flags=re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_PERSON_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b")
_PROJECT_RE = re.compile(
    r"\b(?:project|client|account)\s+([A-Z][A-Za-z0-9_-]+(?:\s+[A-Z][A-Za-z0-9_-]+){0,2})\b"
)
_EMAIL_ADDRESS_RE = re.compile(r"<([^>]+)>")
_ORG_SUFFIXES = ("inc", "llc", "ltd", "gmbh", "sa", "bv", "corp", "company")

_CONTROL_CHECKLIST: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("access_control", ("access control", "least privilege", "role-based access")),
    ("backup_recovery", ("backup", "restore", "disaster recovery")),
    ("incident_response", ("incident response", "security incident", "breach")),
    ("retention", ("retention", "archive", "deletion", "delete after")),
    ("encryption", ("encryption", "encrypted", "tls", "at rest")),
    ("vendor_management", ("vendor", "supplier", "third-party")),
    ("training", ("training", "awareness")),
    ("change_management", ("change management", "approval", "release process")),
)


class ProductIntelligenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.document_repo = DocumentRepository(session)
        self.insight_repo = DocumentInsightRepository(session)
        self.task_repo = WorkflowTaskRepository(session)
        self.graph_repo = KnowledgeGraphRepository(session)

    async def rebuild_document_intelligence(
        self, *, document: Document, parsed_document: ParsedDocument
    ) -> None:
        if not settings.PRODUCT_INTELLIGENCE_ENABLED:
            return
        if settings.PRODUCT_INTELLIGENCE_EXTRACTION_MODE == "off":
            return
        text = parsed_document.text.strip()
        lowered = text.lower()
        metadata = dict(document.metadata_json or {})
        classification = document.document_type or "unclassified"
        confidence = document.document_type_confidence or 0.0
        signals = [
            document.document_type_source,
            document.business_domain,
            document.business_domain_source,
        ]

        classification_insight = DocumentInsight(
            document_id=document.id,
            insight_type="classification",
            title=f"{classification.replace('_', ' ').title()} document",
            summary=document.document_type_reason or "Document classification stored on the document record.",
            confidence=confidence,
            payload_json=intel_prov.merge_provenance(
                {
                    "classification": classification,
                    "document_type": document.document_type,
                    "business_domain": document.business_domain,
                    "signals": signals,
                    "confidence": confidence,
                },
                intel_prov.provenance_block(
                    methods=[
                        intel_prov.METHOD_FILENAME_KEYWORDS,
                        intel_prov.METHOD_BODY_KEYWORDS,
                    ],
                    evidence_tier=intel_prov.EVIDENCE_DOCUMENT_SIGNAL,
                    notes="Type guess from keywords and path; not a verified legal or compliance determination.",
                ),
            ),
        )

        insights: list[DocumentInsight] = [classification_insight]
        meeting_payload = self._extract_meeting_payload(text, metadata)
        contract_payload = self._extract_contract_payload(text)
        compliance_payload = self._extract_compliance_payload(text, classification)

        meeting_insight: DocumentInsight | None = None
        contract_insight: DocumentInsight | None = None
        compliance_insight: DocumentInsight | None = None

        if meeting_payload is not None:
            meeting_payload = intel_prov.merge_provenance(
                dict(meeting_payload),
                intel_prov.provenance_block(
                    methods=[
                        intel_prov.METHOD_BODY_KEYWORDS,
                        intel_prov.METHOD_REGEX_STRUCTURE,
                        intel_prov.METHOD_LINE_ACTION_PARSE,
                        intel_prov.METHOD_EXTRACTIVE_SUMMARY,
                    ],
                    evidence_tier=intel_prov.EVIDENCE_HEURISTIC_PARSE,
                    notes="Extracted from document text using patterns; verify against the source file.",
                ),
            )
            meeting_insight = DocumentInsight(
                document_id=document.id,
                insight_type="meeting_summary",
                title="Meeting summary",
                summary=meeting_payload["summary"],
                confidence=max(confidence, 0.72),
                owner_label=meeting_payload.get("primary_owner"),
                due_at=self._earliest_due_at(meeting_payload.get("action_items", [])),
                payload_json=meeting_payload,
            )
            insights.append(meeting_insight)

        if contract_payload is not None:
            contract_payload = intel_prov.merge_provenance(
                dict(contract_payload),
                intel_prov.provenance_block(
                    methods=[
                        intel_prov.METHOD_BODY_KEYWORDS,
                        intel_prov.METHOD_REGEX_STRUCTURE,
                        intel_prov.METHOD_SENTENCE_MARKER_PARSE,
                        intel_prov.METHOD_EXTRACTIVE_SUMMARY,
                    ],
                    evidence_tier=intel_prov.EVIDENCE_HEURISTIC_PARSE,
                    notes="Obligations and dates are pattern-extracted; legal review required before relying on them.",
                ),
            )
            contract_insight = DocumentInsight(
                document_id=document.id,
                insight_type="contract_summary",
                title="Contract obligations and dates",
                summary=contract_payload["summary"],
                confidence=max(confidence, 0.76),
                owner_label=contract_payload.get("primary_counterparty"),
                due_at=self._earliest_due_at(contract_payload.get("deadlines", [])),
                payload_json=contract_payload,
            )
            insights.append(contract_insight)

        if compliance_payload is not None:
            compliance_payload = intel_prov.merge_provenance(
                dict(compliance_payload),
                intel_prov.provenance_block(
                    methods=[
                        intel_prov.METHOD_BODY_KEYWORDS,
                        intel_prov.METHOD_STATIC_CONTROL_CHECKLIST,
                    ],
                    evidence_tier=intel_prov.EVIDENCE_SUGGESTION,
                    notes="Gaps are missing keyword hits against a static checklist, not an audit finding.",
                ),
            )
            compliance_insight = DocumentInsight(
                document_id=document.id,
                insight_type="compliance_gap_report",
                title="Compliance gap suggestions (unreviewed)",
                summary=compliance_payload["summary"],
                confidence=min(max(confidence, 0.55), 0.72),
                payload_json=compliance_payload,
            )
            insights.append(compliance_insight)

        await self.insight_repo.replace_for_document(document.id, insights)

        tasks = self._build_tasks(
            document=document,
            classification=classification,
            confidence=confidence,
            meeting_insight=meeting_insight,
            meeting_payload=meeting_payload,
            contract_insight=contract_insight,
            contract_payload=contract_payload,
            compliance_insight=compliance_insight,
            compliance_payload=compliance_payload,
        )
        await self.task_repo.replace_for_document(document.id, tasks)

        node_drafts, edge_drafts = self._build_knowledge_graph(
            document=document,
            metadata=metadata,
            meeting_payload=meeting_payload,
            contract_payload=contract_payload,
        )
        await self.graph_repo.replace_document_graph(
            document_id=document.id,
            document_label=document.file_name,
            document_metadata={
                "file_path": document.file_path,
                "classification": classification,
            },
            nodes=node_drafts,
            edges=edge_drafts,
        )

        await self._dispatch_task_hooks(tasks=tasks, document=document)

    async def clear_document_intelligence(self, document_id: UUID | str) -> None:
        if not hasattr(self.session, "execute"):
            return
        await self.insight_repo.delete_for_document(document_id)
        await self.task_repo.delete_for_document(document_id)
        await self.graph_repo.delete_for_document(document_id)
        await self.session.flush()

    async def build_document_detail(
        self,
        *,
        document: Document,
    ) -> DocumentDetail:
        insights = await self.insight_repo.list_by_document(document.id)
        tasks = await self.task_repo.list_by_document(document.id)
        nodes, edges = await self.graph_repo.list_graph_for_document(document.id)
        return DocumentDetail.model_validate(
            {
                **document.__dict__,
                "chunks": document.chunks,
                "insights": insights,
                "workflow_tasks": tasks,
                "knowledge_nodes": nodes,
                "knowledge_edges": edges,
            }
        )

    async def build_overview(self, *, auth: AuthContext) -> IntelligenceOverviewRead:
        if not settings.PRODUCT_INTELLIGENCE_ENABLED:
            return IntelligenceOverviewRead(
                intelligence_feature_enabled=False,
                wedge="disabled",
                document_type_counts={},
                task_status_counts={},
                queue_counts={},
                open_tasks=[],
                spotlight_documents=[],
            )

        documents = await self.document_repo.search(
            auth=auth,
            limit=200,
            include_intelligence=True,
        )
        visible_open_tasks = await self.task_repo.list_open_with_documents_visible_to_auth(
            auth=auth, limit=30
        )

        type_counter: Counter[str] = Counter()
        task_status_counter: Counter[str] = Counter()
        queue_counter: Counter[str] = Counter()
        spotlight_documents: list[IntelligenceSpotlightDocumentRead] = []
        for document in documents:
            insight_types = [insight.insight_type for insight in document.insights]
            classification = document.document_type or self._extract_classification(document.insights)
            if classification and classification != "general":
                type_counter[classification] += 1
            for task in document.workflow_tasks:
                task_status_counter[task.status] += 1
                if task.status in {"queued", "in_progress", "blocked"}:
                    queue_counter[task.queue_name] += 1
            if not insight_types and not document.workflow_tasks:
                continue
            open_doc_tasks = [
                task for task in document.workflow_tasks if task.status in {"queued", "in_progress", "blocked"}
            ]
            spotlight_documents.append(
                IntelligenceSpotlightDocumentRead(
                    document_id=document.id,
                    file_name=document.file_name,
                    file_path=document.file_path,
                    connector_id=document.connector_id,
                    classification=classification,
                    insight_types=insight_types,
                    open_task_count=len(open_doc_tasks),
                    queue_names=sorted({task.queue_name for task in open_doc_tasks}),
                    modified_at=document.modified_at,
                    updated_at=document.updated_at,
                )
            )

        open_task_reads = [
            IntelligenceOpenTaskRead.model_validate(
                {
                    **task_bundle.task.__dict__,
                    "document_file_name": task_bundle.document.file_name
                    if task_bundle.document is not None
                    else None,
                    "document_file_path": task_bundle.document.file_path
                    if task_bundle.document is not None
                    else None,
                    "document_connector_id": task_bundle.document.connector_id
                    if task_bundle.document is not None
                    else None,
                }
            )
            for task_bundle in visible_open_tasks[:25]
        ]
        spotlight_documents.sort(
            key=lambda item: (item.open_task_count, len(item.insight_types), item.updated_at),
            reverse=True,
        )

        return IntelligenceOverviewRead(
            intelligence_feature_enabled=True,
            wedge="contracts-compliance-meetings",
            document_type_counts=dict(type_counter),
            task_status_counts=dict(task_status_counter),
            queue_counts=dict(queue_counter),
            open_tasks=open_task_reads,
            spotlight_documents=spotlight_documents[:12],
        )

    def _classify_document(
        self, *, document: Document, lowered: str
    ) -> tuple[str, float, list[str]]:
        signals: list[str] = []
        scores = Counter[str]()
        haystack = f"{document.file_name.lower()} {document.file_path.lower()} {lowered[:4000]}"

        if document.mime_type == "message/rfc822" or document.file_name.lower().endswith(".eml"):
            scores["email"] += 5
            signals.append("email_source")
        if any(hint in haystack for hint in _MEETING_HINTS):
            scores["meeting"] += 4
            signals.append("meeting_terms")
        if any(hint in haystack for hint in _CONTRACT_HINTS):
            scores["contract"] += 4
            signals.append("contract_terms")
        if any(hint in haystack for hint in _COMPLIANCE_HINTS):
            scores["compliance"] += 4
            signals.append("compliance_terms")
        if any(hint in haystack for hint in _POLICY_HINTS):
            scores["policy"] += 2
            signals.append("policy_terms")

        if "speaker:" in lowered or re.search(r"^[A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,2}:", lowered, flags=re.MULTILINE):
            scores["meeting"] += 3
            signals.append("speaker_pattern")
        if "shall" in lowered or "must" in lowered:
            scores["contract"] += 2
            signals.append("obligation_language")
        if "iso 27001" in lowered or "non-compliant" in lowered:
            scores["compliance"] += 3
            signals.append("standard_gap_terms")

        if not scores:
            return "general", 0.45, ["fallback"]

        classification, score = scores.most_common(1)[0]
        confidence = min(0.95, 0.5 + (score * 0.08))
        return classification, confidence, signals

    def _extract_meeting_payload(
        self, text: str, metadata: dict[str, object]
    ) -> dict[str, object] | None:
        lowered = text.lower()
        if not text.strip():
            return None
        if not any(hint in lowered for hint in _MEETING_HINTS) and not re.search(
            r"^[A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,2}:", text, flags=re.MULTILINE
        ):
            return None

        decisions = self._extract_sentences(
            text, ("decided", "agreed", "approved", "decision"), limit=5
        )
        action_items = self._extract_action_items(text)
        participants = self._extract_people(text)
        if from_header := str(metadata.get("from") or ""):
            participants.extend(self._extract_people(from_header))
        participants = list(dict.fromkeys(participants))[:10]
        summary = self._summarize_text(text, fallback_sentences=decisions, max_sentences=2)
        primary_owner = action_items[0]["owner_label"] if action_items and action_items[0].get("owner_label") else None
        return {
            "summary": summary,
            "decisions": decisions,
            "action_items": action_items,
            "participants": participants,
            "primary_owner": primary_owner,
        }

    def _extract_contract_payload(self, text: str) -> dict[str, object] | None:
        lowered = text.lower()
        if not any(hint in lowered for hint in _CONTRACT_HINTS) and "shall" not in lowered and "must" not in lowered:
            return None

        obligations = self._extract_sentences(
            text, (" shall ", " must ", " agrees to ", " responsible for "), limit=6
        )
        deadlines = self._extract_deadlines(text)
        renewal_terms = self._extract_sentences(
            text, ("renew", "auto-renew", "renewal", "term"), limit=4
        )
        penalties = self._extract_sentences(
            text, ("penalty", "liquidated damages", "termination fee", "late fee", "interest"), limit=4
        )
        counterparties = self._extract_counterparties(text)
        summary = self._summarize_text(
            "\n".join([*obligations[:2], *renewal_terms[:1], *penalties[:1]]) or text,
            fallback_sentences=obligations or renewal_terms,
            max_sentences=2,
        )
        return {
            "summary": summary,
            "counterparties": counterparties,
            "obligations": obligations,
            "deadlines": deadlines,
            "renewal_terms": renewal_terms,
            "penalties": penalties,
            "primary_counterparty": counterparties[0] if counterparties else None,
        }

    def _extract_compliance_payload(
        self, text: str, classification: str
    ) -> dict[str, object] | None:
        lowered = text.lower()
        if classification not in {"contract", "compliance", "policy"} and not any(
            hint in lowered for hint in _COMPLIANCE_HINTS
        ):
            return None

        covered_controls: list[str] = []
        gap_controls: list[str] = []
        for control_name, keywords in _CONTROL_CHECKLIST:
            if any(keyword in lowered for keyword in keywords):
                covered_controls.append(control_name)
            else:
                gap_controls.append(control_name)
        coverage_ratio = len(covered_controls) / max(len(_CONTROL_CHECKLIST), 1)
        severity = "high" if len(gap_controls) >= 5 else "medium" if gap_controls else "low"
        summary = (
            "Suggestion (keyword checklist only, not an audit): "
            f"coverage {len(covered_controls)}/{len(_CONTROL_CHECKLIST)} checklist items matched in text. "
            f"Items without keyword hits: {', '.join(gap_controls[:4]) or 'none'}."
        )
        return {
            "summary": summary,
            "covered_controls": covered_controls,
            "gap_controls": gap_controls,
            "severity": severity,
            "coverage_ratio": round(coverage_ratio, 3),
        }

    def _build_tasks(
        self,
        *,
        document: Document,
        classification: str,
        confidence: float,
        meeting_insight: DocumentInsight | None,
        meeting_payload: dict[str, object] | None,
        contract_insight: DocumentInsight | None,
        contract_payload: dict[str, object] | None,
        compliance_insight: DocumentInsight | None,
        compliance_payload: dict[str, object] | None,
    ) -> list[WorkflowTask]:
        tasks: list[WorkflowTask] = []

        if meeting_insight and meeting_payload:
            for action_item in meeting_payload.get("action_items", [])[:8]:
                title = str(action_item.get("title") or "").strip()
                if not title:
                    continue
                due_at = self._parse_date(str(action_item.get("due_at") or ""))
                tasks.append(
                    WorkflowTask(
                        document_id=document.id,
                        insight_id=meeting_insight.id,
                        task_type="meeting_action_item",
                        queue_name="meetings",
                        title=title[:255],
                        description=str(action_item.get("detail") or title),
                        status="queued",
                        priority=self._priority_for_due_at(due_at),
                        owner_label=str(action_item.get("owner_label") or "") or None,
                        due_at=due_at,
                        metadata_json=intel_prov.task_metadata_with_provenance(
                            dict(action_item) if isinstance(action_item, dict) else {},
                            methods=[
                                intel_prov.METHOD_LINE_ACTION_PARSE,
                                intel_prov.METHOD_REGEX_STRUCTURE,
                            ],
                            evidence_tier=intel_prov.EVIDENCE_HEURISTIC_PARSE,
                            presentation="action_candidate",
                            notes="Parsed from meeting text; confirm owner and due date.",
                        ),
                    )
                )

        if contract_insight and contract_payload:
            for deadline in contract_payload.get("deadlines", [])[:6]:
                title = str(deadline.get("title") or deadline.get("sentence") or "").strip()
                if not title:
                    continue
                due_at = self._parse_date(str(deadline.get("due_at") or ""))
                tasks.append(
                    WorkflowTask(
                        document_id=document.id,
                        insight_id=contract_insight.id,
                        task_type="contract_deadline",
                        queue_name="contracts",
                        title=title[:255],
                        description=str(deadline.get("sentence") or title),
                        status="queued",
                        priority=self._priority_for_due_at(due_at),
                        owner_label=str(deadline.get("owner_label") or "") or None,
                        due_at=due_at,
                        metadata_json=intel_prov.task_metadata_with_provenance(
                            dict(deadline) if isinstance(deadline, dict) else {},
                            methods=[
                                intel_prov.METHOD_SENTENCE_MARKER_PARSE,
                                intel_prov.METHOD_REGEX_STRUCTURE,
                            ],
                            evidence_tier=intel_prov.EVIDENCE_HEURISTIC_PARSE,
                            presentation="deadline_candidate",
                            notes="Date extracted by pattern; verify in the contract body.",
                        ),
                    )
                )

            if contract_payload.get("renewal_terms"):
                tasks.append(
                    WorkflowTask(
                        document_id=document.id,
                        insight_id=contract_insight.id,
                        task_type="contract_review",
                        queue_name="contracts",
                        title="Review renewal and commercial terms",
                        description=str(contract_payload["renewal_terms"][0]),
                        status="queued",
                        priority="normal",
                        owner_label=str(contract_payload.get("primary_counterparty") or "") or None,
                        metadata_json=intel_prov.task_metadata_with_provenance(
                            {"source": "renewal_terms"},
                            methods=[intel_prov.METHOD_SENTENCE_MARKER_PARSE],
                            evidence_tier=intel_prov.EVIDENCE_HEURISTIC_PARSE,
                            presentation="review_candidate",
                        ),
                    )
                )

        if compliance_insight and compliance_payload:
            for gap_name in list(compliance_payload.get("gap_controls", []))[:4]:
                tasks.append(
                    WorkflowTask(
                        document_id=document.id,
                        insight_id=compliance_insight.id,
                        task_type="compliance_gap",
                        queue_name="compliance",
                        title=f"Suggest verifying: {gap_name.replace('_', ' ')}",
                        description=(
                            "Keyword checklist did not find typical markers for this topic in the document text. "
                            "Treat as a suggestion until reviewed; it is not proof of non-compliance."
                        ),
                        status="queued",
                        priority="low",
                        metadata_json=intel_prov.task_metadata_with_provenance(
                            {"gap_control": gap_name, "checklist_severity": compliance_payload.get("severity")},
                            methods=[intel_prov.METHOD_STATIC_CONTROL_CHECKLIST],
                            evidence_tier=intel_prov.EVIDENCE_SUGGESTION,
                            presentation="suggestion",
                        ),
                    )
                )

        if classification != "general" or confidence < 0.65:
            tasks.append(
                WorkflowTask(
                    document_id=document.id,
                    insight_id=None,
                    task_type="triage_review",
                    queue_name="triage",
                    title=f"Triage {classification.replace('_', ' ')} document",
                    description=(
                        "Confirm classification, assign owner, and decide whether this document "
                        "needs meeting, contract, or compliance follow-up."
                    ),
                    status="queued",
                    priority="normal",
                    metadata_json=intel_prov.task_metadata_with_provenance(
                        {"classification": classification, "confidence": confidence},
                        methods=[
                            intel_prov.METHOD_FILENAME_KEYWORDS,
                            intel_prov.METHOD_BODY_KEYWORDS,
                        ],
                        evidence_tier=intel_prov.EVIDENCE_SUGGESTION,
                        presentation="suggestion",
                    ),
                )
            )

        return tasks

    def _build_knowledge_graph(
        self,
        *,
        document: Document,
        metadata: dict[str, object],
        meeting_payload: dict[str, object] | None,
        contract_payload: dict[str, object] | None,
    ) -> tuple[list[KnowledgeNodeDraft], list[KnowledgeEdgeDraft]]:
        connector_id = document.connector_id
        nodes: list[KnowledgeNodeDraft] = []
        edges: list[KnowledgeEdgeDraft] = []
        seen_nodes: set[tuple[str, str]] = set()

        def add_node(node_type: str, label: str, *, metadata_json: dict | None = None) -> tuple[str, str]:
            external_key = self._scoped_graph_external_key(connector_id, node_type, label)
            key = (node_type, external_key)
            if key not in seen_nodes:
                seen_nodes.add(key)
                base_meta = {
                    **(metadata_json or {}),
                    "connector_id": str(connector_id),
                }
                nodes.append(
                    KnowledgeNodeDraft(
                        node_type=node_type,
                        external_key=external_key,
                        label=label,
                        metadata_json=intel_prov.merge_provenance(
                            base_meta,
                            intel_prov.provenance_block(
                                methods=[intel_prov.METHOD_GRAPH_CO_MENTION],
                                evidence_tier=intel_prov.EVIDENCE_SUGGESTION,
                                notes="Entity node scoped to connector; deduplicated only within this connector.",
                            ),
                        ),
                    )
                )
            return key

        def add_edge(target_key: tuple[str, str], relation_type: str, *, metadata_json: dict | None = None) -> None:
            edges.append(
                KnowledgeEdgeDraft(
                    source_key=("document", str(document.id)),
                    target_key=target_key,
                    relation_type=relation_type,
                    metadata_json=intel_prov.merge_provenance(
                        dict(metadata_json or {}),
                        intel_prov.provenance_block(
                            methods=[intel_prov.METHOD_GRAPH_CO_MENTION],
                            evidence_tier=intel_prov.EVIDENCE_SUGGESTION,
                            notes="Edge from the same indexed document extraction pass.",
                        ),
                    ),
                )
            )

        thread_key = str(metadata.get("thread_key") or "").strip()
        if thread_key:
            target = add_node("thread", thread_key)
            add_edge(target, "belongs_to_thread")

        if meeting_payload:
            for participant in list(meeting_payload.get("participants") or [])[:12]:
                p = str(participant).strip()
                if p:
                    target = add_node("person", p)
                    add_edge(target, "mentions_person")
        else:
            for participant in self._extract_people(
                "\n".join(
                    [
                        document.file_name,
                        document.file_path,
                        str(metadata),
                    ]
                )
            ):
                target = add_node("person", participant)
                add_edge(target, "mentions_person")

        for organization in self._extract_counterparties(str(contract_payload or "")):
            target = add_node("organization", organization)
            add_edge(target, "mentions_organization")

        for project in self._extract_projects(
            "\n".join(
                filter(
                    None,
                    [
                        document.file_name,
                        document.file_path,
                        str(metadata),
                        str(meeting_payload or ""),
                        str(contract_payload or ""),
                    ],
                )
            )
        ):
            target = add_node("project", project)
            add_edge(target, "related_to_project")

        for address in _EMAIL_ADDRESS_RE.findall(str(metadata.get("from") or "")):
            domain = address.split("@")[-1].split(".")[0].strip()
            if domain:
                target = add_node("organization", domain.title())
                add_edge(target, "sender_domain")

        return nodes, edges

    async def _dispatch_task_hooks(
        self, *, tasks: list[WorkflowTask], document: Document
    ) -> None:
        if not settings.TASK_WEBHOOK_URL or not tasks:
            return

        async with httpx.AsyncClient(timeout=settings.TASK_WEBHOOK_TIMEOUT_SECONDS) as client:
            for task in tasks:
                payload = {
                    "task_id": str(task.id),
                    "document_id": str(document.id),
                    "file_name": document.file_name,
                    "file_path": document.file_path,
                    "queue_name": task.queue_name,
                    "task_type": task.task_type,
                    "title": task.title,
                    "description": task.description,
                    "owner_label": task.owner_label,
                    "due_at": task.due_at.isoformat() if task.due_at else None,
                    "metadata_json": task.metadata_json,
                }
                try:
                    response = await client.post(settings.TASK_WEBHOOK_URL, json=payload)
                    response.raise_for_status()
                    task.hook_status = "delivered"
                    task.hook_response = f"HTTP {response.status_code}"
                except Exception as exc:
                    logger.warning("Task webhook delivery failed for task %s: %s", task.id, exc)
                    task.hook_status = "failed"
                    task.hook_response = str(exc)[:500]
                task.hook_last_attempt_at = datetime.now(UTC)
        await self.session.flush()

    @staticmethod
    def _extract_classification(insights: Iterable[DocumentInsight]) -> str | None:
        for insight in insights:
            if insight.insight_type != "classification":
                continue
            payload = insight.payload_json or {}
            classification = payload.get("classification")
            if isinstance(classification, str) and classification:
                return classification
        return None

    @staticmethod
    def _extract_sentences(
        text: str, markers: tuple[str, ...], *, limit: int
    ) -> list[str]:
        results: list[str] = []
        for sentence in _SENTENCE_RE.split(text):
            normalized = " ".join(sentence.split())
            lowered = f" {normalized.lower()} "
            if not normalized:
                continue
            if any(marker in lowered for marker in markers):
                results.append(normalized[:500])
            if len(results) >= limit:
                break
        return results

    def _extract_action_items(self, text: str) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        candidates = [
            *text.splitlines(),
            *_SENTENCE_RE.split(text),
        ]
        for raw_candidate in candidates:
            normalized = " ".join(raw_candidate.split()).strip("-* ")
            lowered = normalized.lower()
            if not normalized:
                continue
            if "action item:" in lowered:
                title = normalized.split("Action item:", 1)[-1].split("action item:", 1)[-1].strip()
            elif lowered.startswith(("todo", "next step")):
                title = normalized.split(":", 1)[-1].strip()
            elif re.match(r"^[A-Z][a-z]+(?: [A-Z][a-z]+){0,2}\s+(?:to|will)\s+", normalized):
                title = normalized
            else:
                continue
            owner_match = re.match(
                r"^(?P<owner>[A-Z][a-z]+(?: [A-Z][a-z]+){0,2})\s+(?:to|will)\s+(?P<task>.+)$",
                title,
            )
            due_match = _DATE_RE.search(title)
            item = {
                "title": (owner_match.group("task") if owner_match else title)[:255],
                "detail": normalized[:500],
                "owner_label": owner_match.group("owner") if owner_match else None,
                "due_at": due_match.group(0) if due_match else None,
            }
            if item not in items:
                items.append(item)
            if len(items) >= 8:
                break
        return items

    def _extract_deadlines(self, text: str) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        markers = ("by ", "within ", "no later than", "renewal", "effective date", "termination")
        for sentence in _SENTENCE_RE.split(text):
            normalized = " ".join(sentence.split())
            lowered = normalized.lower()
            if not normalized or not any(marker in lowered for marker in markers):
                continue
            due_match = _DATE_RE.search(normalized)
            results.append(
                {
                    "title": normalized[:255],
                    "sentence": normalized[:500],
                    "due_at": due_match.group(0) if due_match else None,
                    "owner_label": None,
                }
            )
            if len(results) >= 6:
                break
        return results

    @staticmethod
    def _extract_counterparties(text: str) -> list[str]:
        matches: list[str] = []
        between_match = re.search(
            r"between\s+(.+?)\s+and\s+(.+?)(?:[.;,\n]|$)",
            text,
            flags=re.IGNORECASE,
        )
        if between_match:
            for candidate in between_match.groups():
                cleaned = " ".join(candidate.split()).strip(" .,:;")
                if cleaned and cleaned not in matches:
                    matches.append(cleaned)
        for candidate in _PERSON_RE.findall(text):
            lowered = candidate.lower()
            if any(lowered.endswith(suffix) for suffix in _ORG_SUFFIXES):
                matches.append(candidate)
        return list(dict.fromkeys(matches))[:6]

    @staticmethod
    def _extract_people(text: str) -> list[str]:
        names: list[str] = []
        for candidate in _PERSON_RE.findall(text):
            normalized = " ".join(candidate.split())
            if normalized.lower() in {"subject", "from", "date", "attachments", "action items"}:
                continue
            if normalized not in names:
                names.append(normalized)
        return names[:10]

    @staticmethod
    def _extract_projects(text: str) -> list[str]:
        return list(dict.fromkeys(match.strip() for match in _PROJECT_RE.findall(text)))[:8]

    @staticmethod
    def _summarize_text(
        text: str,
        *,
        fallback_sentences: list[str] | None = None,
        max_sentences: int = 2,
    ) -> str:
        candidates = [
            " ".join(sentence.split())
            for sentence in _SENTENCE_RE.split(text)
            if len(sentence.split()) >= 5
        ]
        selected = candidates[:max_sentences] or (fallback_sentences or [])[:max_sentences]
        summary = " ".join(selected).strip()
        return summary[:800] if summary else "No summary available."

    @staticmethod
    def _parse_date(raw_value: str) -> datetime | None:
        value = raw_value.strip()
        if not value:
            return None
        for pattern in _DATE_PATTERNS:
            try:
                return datetime.strptime(value, pattern).replace(tzinfo=UTC)
            except ValueError:
                continue
        return None

    @classmethod
    def _earliest_due_at(cls, items: list[dict[str, object]]) -> datetime | None:
        dates = [
            parsed
            for parsed in (
                cls._parse_date(str(item.get("due_at") or "")) for item in items
            )
            if parsed is not None
        ]
        return min(dates) if dates else None

    @staticmethod
    def _priority_for_due_at(due_at: datetime | None) -> str:
        if due_at is None:
            return "normal"
        if due_at <= datetime.now(UTC) + timedelta(days=14):
            return "high"
        return "normal"

    @staticmethod
    def _node_key(node_type: str, label: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or node_type

    @staticmethod
    def _scoped_graph_external_key(connector_id: UUID, node_type: str, label: str) -> str:
        slug = ProductIntelligenceService._node_key(node_type, label)
        raw = f"{connector_id}:{node_type}:{slug}"
        return raw[:240]
