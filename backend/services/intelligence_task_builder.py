"""Validated workflow-task construction for product intelligence outputs."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..db.models import Document, DocumentInsight, WorkflowTask
from . import intelligence_provenance as intel_prov
from .intelligence_task_policy import (
    acceptance_criteria,
    parse_task_date,
    priority_for_due_at,
    suggested_owner_roles,
    suggested_reviewer_roles,
    task_title_from_excerpt,
)
from .task_validation import (
    EvidenceItem,
    TaskCandidate,
    task_validation_metadata,
    validate_candidate,
)

EvidenceFactory = Callable[..., EvidenceItem]


class IntelligenceTaskBuilder:
    def __init__(
        self,
        *,
        document: Document,
        evidence_factory: EvidenceFactory,
    ) -> None:
        self.document = document
        self.evidence_item = evidence_factory
        self.tasks: list[WorkflowTask] = []

    def add_candidate(
        self,
        candidate: TaskCandidate,
        *,
        insight: DocumentInsight | None,
        queue_name: str,
        priority: str,
        owner_label: str | None = None,
        due_at: datetime | None = None,
        methods: list[str],
        evidence_tier: str,
        presentation: str,
        description: str | None = None,
    ) -> None:
        validated = validate_candidate(candidate)
        if validated is None:
            return
        task_payload: dict[str, Any] = dict(candidate.suggested_task_payload)
        task_payload.update(task_validation_metadata(validated))
        review_status = validated.status
        effective_priority = "low" if review_status == "suggested" else priority
        effective_presentation = (
            "suggestion" if review_status == "suggested" else presentation
        )
        task_payload.update(
            {
                "workflow_stage": "queued",
                "review_status": review_status,
                "blocked_by_task_ids": [],
                "acceptance_criteria": acceptance_criteria(
                    task_type=candidate.candidate_type,
                    review_status=review_status,
                ),
                "suggested_owner_roles": suggested_owner_roles(
                    queue_name=queue_name,
                    task_type=candidate.candidate_type,
                ),
                "suggested_reviewer_roles": suggested_reviewer_roles(
                    queue_name=queue_name,
                    task_type=candidate.candidate_type,
                ),
            }
        )
        self.tasks.append(
            WorkflowTask(
                id=uuid.uuid4(),
                document_id=self.document.id,
                insight_id=insight.id if insight is not None else None,
                task_type=candidate.candidate_type,
                queue_name=queue_name,
                title=candidate.normalized_title[:255],
                description=description or candidate.extracted_claim,
                status="queued",
                priority=effective_priority,
                owner_label=owner_label,
                due_at=due_at,
                metadata_json=intel_prov.task_metadata_with_provenance(
                    task_payload,
                    methods=methods,
                    evidence_tier=evidence_tier,
                    presentation=effective_presentation,
                    notes=validated.reason,
                ),
            )
        )

    def attach_manager_triage(self) -> None:
        triage_targets = [
            task
            for task in self.tasks
            if task.task_type != "manager_triage_assignment"
            and (
                not (task.owner_label or "").strip()
                or task.priority in {"high", "urgent", "critical"}
            )
        ]
        if not triage_targets:
            return

        triage_task_id = uuid.uuid4()
        blocked_task_ids = [str(task.id) for task in triage_targets if task.id]
        earliest_due = min(
            (task.due_at for task in triage_targets if task.due_at is not None),
            default=None,
        )
        triage_priority = (
            "high"
            if any(task.priority == "high" for task in triage_targets)
            else "normal"
        )
        triage_payload = {
            "workflow_stage": "queued",
            "review_status": "needs_review",
            "blocked_by_task_ids": [],
            "blocked_task_ids": blocked_task_ids,
            "acceptance_criteria": acceptance_criteria(
                task_type="manager_triage_assignment",
                review_status="needs_review",
            ),
            "suggested_owner_roles": ["manager", "project_manager", "team_lead"],
            "suggested_reviewer_roles": [
                "operations_manager",
                "compliance_lead",
            ],
            "triage_reason": (
                "Auto-generated because one or more tasks are unassigned "
                "or high-priority."
            ),
        }
        self.tasks.append(
            WorkflowTask(
                id=triage_task_id,
                document_id=self.document.id,
                task_type="manager_triage_assignment",
                queue_name="manager_triage",
                title=f"Assign owner/reviewer for {len(triage_targets)} queued tasks",
                description=(
                    "Manager triage required before execution: assign owner and "
                    "reviewer, confirm acceptance checklist, and unblock linked tasks."
                ),
                status="queued",
                priority=triage_priority,
                owner_label="Manager",
                due_at=earliest_due,
                metadata_json=intel_prov.task_metadata_with_provenance(
                    triage_payload,
                    methods=[intel_prov.METHOD_STATIC_CONTROL_CHECKLIST],
                    evidence_tier=intel_prov.EVIDENCE_SUGGESTION,
                    presentation="triage",
                    notes="Auto triage to route ownership and review accountability.",
                ),
            )
        )

        triage_task_id_value = str(triage_task_id)
        for task in triage_targets:
            meta = dict(task.metadata_json or {})
            existing_blockers = meta.get("blocked_by_task_ids")
            blockers = (
                [str(value) for value in existing_blockers if isinstance(value, str)]
                if isinstance(existing_blockers, list)
                else []
            )
            if triage_task_id_value not in blockers:
                blockers.append(triage_task_id_value)
            meta["blocked_by_task_ids"] = blockers
            meta["workflow_stage"] = "awaiting_manager_triage"
            task.metadata_json = meta

    def populate_from_insights(
        self,
        *,
        classification: str,
        confidence: float,
        meeting_insight: DocumentInsight | None,
        meeting_payload: dict[str, object] | None,
        contract_insight: DocumentInsight | None,
        contract_payload: dict[str, object] | None,
        compliance_insight: DocumentInsight | None,
        compliance_payload: dict[str, object] | None,
    ) -> list[WorkflowTask]:
        """Materialize typed task candidates from extracted insight payloads."""
        document = self.document
        if meeting_insight and meeting_payload:
            for action_item in meeting_payload.get("action_items", [])[:8]:
                title = str(action_item.get("title") or "").strip()
                if not title:
                    continue
                due_at = parse_task_date(str(action_item.get("due_at") or ""))
                excerpt = str(action_item.get("detail") or title)
                self.add_candidate(
                    TaskCandidate(
                        candidate_id=f"{document.id}:meeting_action:{len(self.tasks)}",
                        source_document_id=document.id,
                        candidate_type="meeting_action_item",
                        extracted_claim=excerpt,
                        normalized_title=title,
                        source_excerpt=excerpt,
                        evidence_method=intel_prov.METHOD_LINE_ACTION_PARSE,
                        evidence_items=[
                            self.evidence_item(
                                document=document,
                                excerpt=excerpt,
                                signal_type="direct_quote",
                                score=0.86,
                            )
                        ],
                        suggested_task_payload=dict(action_item)
                        if isinstance(action_item, dict)
                        else {},
                        keyword_overlap=0.82,
                        source_agreement=0.70,
                        document_classification_confidence=confidence,
                    ),
                    insight=meeting_insight,
                    queue_name="meetings",
                    priority=priority_for_due_at(due_at),
                    owner_label=str(action_item.get("owner_label") or "") or None,
                    due_at=due_at,
                    methods=[
                        intel_prov.METHOD_LINE_ACTION_PARSE,
                        intel_prov.METHOD_REGEX_STRUCTURE,
                    ],
                    evidence_tier=intel_prov.EVIDENCE_HEURISTIC_PARSE,
                    presentation="action_candidate",
                )

        if contract_insight and contract_payload:
            for deadline in contract_payload.get("deadlines", [])[:6]:
                title = str(
                    deadline.get("title") or deadline.get("sentence") or ""
                ).strip()
                if not title:
                    continue
                due_at = parse_task_date(str(deadline.get("due_at") or ""))
                excerpt = str(deadline.get("sentence") or title)
                self.add_candidate(
                    TaskCandidate(
                        candidate_id=f"{document.id}:contract_deadline:{len(self.tasks)}",
                        source_document_id=document.id,
                        candidate_type="contract_deadline",
                        extracted_claim=excerpt,
                        normalized_title=title,
                        source_excerpt=excerpt,
                        evidence_method=intel_prov.METHOD_SENTENCE_MARKER_PARSE,
                        evidence_items=[
                            self.evidence_item(
                                document=document,
                                excerpt=excerpt,
                                signal_type="direct_quote",
                                score=0.84,
                            )
                        ],
                        suggested_task_payload=dict(deadline)
                        if isinstance(deadline, dict)
                        else {},
                        keyword_overlap=0.78,
                        source_agreement=0.65,
                        document_classification_confidence=confidence,
                    ),
                    insight=contract_insight,
                    queue_name="contracts",
                    priority=priority_for_due_at(due_at),
                    owner_label=str(deadline.get("owner_label") or "") or None,
                    due_at=due_at,
                    methods=[
                        intel_prov.METHOD_SENTENCE_MARKER_PARSE,
                        intel_prov.METHOD_REGEX_STRUCTURE,
                    ],
                    evidence_tier=intel_prov.EVIDENCE_HEURISTIC_PARSE,
                    presentation="deadline_candidate",
                )

            for index, obligation in enumerate(
                list(contract_payload.get("obligations", []))[:4]
            ):
                excerpt = str(obligation).strip()
                if not excerpt:
                    continue
                title = task_title_from_excerpt(excerpt, prefix="Review obligation")
                self.add_candidate(
                    TaskCandidate(
                        candidate_id=f"{document.id}:contract_obligation:{index}",
                        source_document_id=document.id,
                        candidate_type="contract_obligation_review",
                        extracted_claim=excerpt,
                        normalized_title=title,
                        source_excerpt=excerpt,
                        evidence_method=intel_prov.METHOD_SENTENCE_MARKER_PARSE,
                        evidence_items=[
                            self.evidence_item(
                                document=document,
                                excerpt=excerpt,
                                signal_type="direct_quote",
                                score=0.82,
                            )
                        ],
                        suggested_task_payload={
                            "source": "obligations",
                            "obligation": excerpt,
                        },
                        keyword_overlap=0.80,
                        source_agreement=0.60,
                        document_classification_confidence=confidence,
                    ),
                    insight=contract_insight,
                    queue_name="contracts",
                    priority="normal",
                    methods=[intel_prov.METHOD_SENTENCE_MARKER_PARSE],
                    evidence_tier=intel_prov.EVIDENCE_HEURISTIC_PARSE,
                    presentation="review_candidate",
                )

            if contract_payload.get("renewal_terms"):
                excerpt = str(contract_payload["renewal_terms"][0])
                self.add_candidate(
                    TaskCandidate(
                        candidate_id=f"{document.id}:contract_renewal",
                        source_document_id=document.id,
                        candidate_type="contract_review",
                        extracted_claim=excerpt,
                        normalized_title="Review renewal and commercial terms",
                        source_excerpt=excerpt,
                        evidence_method=intel_prov.METHOD_SENTENCE_MARKER_PARSE,
                        evidence_items=[
                            self.evidence_item(
                                document=document,
                                excerpt=excerpt,
                                signal_type="direct_quote",
                                score=0.78,
                            )
                        ],
                        suggested_task_payload={
                            "source": "renewal_terms",
                            "renewal_term": excerpt,
                        },
                        keyword_overlap=0.72,
                        source_agreement=0.55,
                        document_classification_confidence=confidence,
                    ),
                    insight=contract_insight,
                    queue_name="contracts",
                    priority="normal",
                    owner_label=str(contract_payload.get("primary_counterparty") or "")
                    or None,
                    methods=[intel_prov.METHOD_SENTENCE_MARKER_PARSE],
                    evidence_tier=intel_prov.EVIDENCE_HEURISTIC_PARSE,
                    presentation="review_candidate",
                )

        if compliance_insight and compliance_payload:
            for gap_name in list(compliance_payload.get("gap_controls", []))[:4]:
                description = (
                    "Static checklist did not find typical markers for this topic. "
                    "This is an unverified review suggestion, not proof of non-compliance."
                )
                self.add_candidate(
                    TaskCandidate(
                        candidate_id=f"{document.id}:compliance_suggestion:{gap_name}",
                        source_document_id=document.id,
                        candidate_type="compliance_review_suggestion",
                        extracted_claim=description,
                        normalized_title=(
                            f"Review whether {gap_name.replace('_', ' ')} applies"
                        ),
                        source_excerpt="",
                        evidence_method=intel_prov.METHOD_STATIC_CONTROL_CHECKLIST,
                        evidence_items=[
                            self.evidence_item(
                                document=document,
                                excerpt="",
                                signal_type="missing_keyword",
                                score=0.10,
                            )
                        ],
                        suggested_task_payload={
                            "gap_control": gap_name,
                            "checklist_severity": compliance_payload.get("severity"),
                        },
                        keyword_overlap=0.0,
                        source_agreement=0.0,
                        document_classification_confidence=confidence,
                        unverified_suggestion=True,
                    ),
                    insight=compliance_insight,
                    queue_name="compliance",
                    priority="low",
                    methods=[intel_prov.METHOD_STATIC_CONTROL_CHECKLIST],
                    evidence_tier=intel_prov.EVIDENCE_SUGGESTION,
                    presentation="suggestion",
                    description=description,
                )

        if classification not in {"general", "unclassified"} and confidence < 0.65:
            self.add_candidate(
                TaskCandidate(
                    candidate_id=f"{document.id}:classification_triage",
                    source_document_id=document.id,
                    candidate_type="triage_review",
                    extracted_claim=(
                        "Classification is low confidence; human review should decide "
                        "whether workflow follow-up is needed."
                    ),
                    normalized_title=(
                        f"Review {classification.replace('_', ' ')} classification"
                    ),
                    source_excerpt="",
                    evidence_method=intel_prov.METHOD_FILENAME_KEYWORDS,
                    evidence_items=[
                        self.evidence_item(
                            document=document,
                            excerpt="",
                            signal_type="metadata_match",
                            score=0.18,
                        )
                    ],
                    suggested_task_payload={
                        "classification": classification,
                        "confidence": confidence,
                    },
                    document_classification_confidence=confidence,
                    unverified_suggestion=True,
                ),
                insight=None,
                queue_name="triage",
                priority="low",
                methods=[
                    intel_prov.METHOD_FILENAME_KEYWORDS,
                    intel_prov.METHOD_BODY_KEYWORDS,
                ],
                evidence_tier=intel_prov.EVIDENCE_SUGGESTION,
                presentation="suggestion",
                description=(
                    "Classification evidence is weak. Review before creating any "
                    "downstream task."
                ),
            )

        self.attach_manager_triage()
        return self.tasks
