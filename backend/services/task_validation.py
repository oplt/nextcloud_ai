from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


CONFIDENCE_PROMOTION_THRESHOLD = 0.62
CONFIDENCE_REVIEW_THRESHOLD = 0.30

DIRECT_SIGNAL_TYPES = {"direct_quote", "semantic_match"}
WEAK_SIGNAL_TYPES = {"keyword_match", "metadata_match", "missing_keyword"}

METHOD_RELIABILITY = {
    "line_action_item_parse": 0.72,
    "sentence_marker_parse": 0.68,
    "regex_structure": 0.62,
    "body_keyword_signals": 0.46,
    "filename_path_keyword_signals": 0.28,
    "static_control_keyword_checklist": 0.18,
}


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    document_id: UUID | str | None
    file_name: str | None
    file_path: str | None
    chunk_id: UUID | str | None
    page_number: int | None
    excerpt: str
    signal_type: str
    score: float
    heading_path: str | None = None
    section_title: str | None = None
    retrieval_score: float | None = None
    rerank_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": str(self.document_id) if self.document_id else None,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "chunk_id": str(self.chunk_id) if self.chunk_id else None,
            "page_number": self.page_number,
            "excerpt": self.excerpt,
            "signal_type": self.signal_type,
            "score": round(_clamp(self.score), 4),
            "heading_path": self.heading_path,
            "section_title": self.section_title,
            "retrieval_score": self.retrieval_score,
            "rerank_score": self.rerank_score,
        }


@dataclass(slots=True)
class TaskCandidate:
    candidate_id: str
    source_document_id: UUID | str | None
    candidate_type: str
    extracted_claim: str
    normalized_title: str
    source_excerpt: str
    evidence_method: str
    evidence_items: list[EvidenceItem]
    suggested_task_payload: dict[str, Any]
    keyword_overlap: float = 0.0
    source_agreement: float = 0.0
    document_classification_confidence: float = 0.0
    confidence_score: float | None = None
    confidence_reasons: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    unverified_suggestion: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source_document_id": str(self.source_document_id) if self.source_document_id else None,
            "candidate_type": self.candidate_type,
            "extracted_claim": self.extracted_claim,
            "normalized_title": self.normalized_title,
            "source_excerpt": self.source_excerpt,
            "evidence_method": self.evidence_method,
            "confidence_score": round(self.confidence_score or 0.0, 4),
            "confidence_reasons": list(self.confidence_reasons),
            "risk_flags": list(self.risk_flags),
            "suggested_task_payload": dict(self.suggested_task_payload),
            "evidence_items": [item.as_dict() for item in self.evidence_items],
            "unverified_suggestion": self.unverified_suggestion,
        }


@dataclass(frozen=True, slots=True)
class ValidatedTask:
    candidate: TaskCandidate
    status: str
    confidence_level: str
    confidence_score: float
    reason: str
    recommended_action: str


def score_candidate(candidate: TaskCandidate) -> float:
    """Combine available signals without pretending absent rerank/retrieval scores exist."""
    candidate.confidence_reasons.clear()
    candidate.risk_flags.clear()
    evidence = candidate.evidence_items
    direct_count = sum(1 for item in evidence if item.signal_type in DIRECT_SIGNAL_TYPES and item.excerpt)
    keyword_only = evidence and all(item.signal_type in WEAK_SIGNAL_TYPES for item in evidence)
    missing_keyword = any(item.signal_type == "missing_keyword" for item in evidence)
    chunks = {str(item.chunk_id) for item in evidence if item.chunk_id}

    retrieval_score = max((item.retrieval_score or 0.0 for item in evidence), default=0.0)
    rerank_score = max((item.rerank_score or 0.0 for item in evidence), default=0.0)
    evidence_score = max((item.score for item in evidence), default=0.0)
    method_score = METHOD_RELIABILITY.get(candidate.evidence_method, 0.35)

    score = 0.0
    score += 0.24 * _clamp(evidence_score)
    score += 0.12 * _clamp(retrieval_score)
    score += 0.14 * _clamp(rerank_score)
    score += 0.12 * _clamp(candidate.keyword_overlap)
    score += 0.10 * min(len(chunks), 3) / 3
    score += 0.10 * _clamp(candidate.source_agreement)
    score += 0.10 * _clamp(candidate.document_classification_confidence)
    score += 0.18 * _clamp(method_score)

    if direct_count:
        score += 0.14
        candidate.confidence_reasons.append("direct source excerpt present")
    if len(chunks) > 1:
        score += 0.06
        candidate.confidence_reasons.append("multiple chunks support the claim")
    if rerank_score and retrieval_score:
        score += 0.06
        candidate.confidence_reasons.append("retrieval and rerank signals agree")
    if keyword_only:
        score = min(score, 0.48)
        candidate.risk_flags.append("keyword_only")
    if missing_keyword:
        score = min(score, 0.28)
        candidate.risk_flags.append("missing_keyword_not_factual_finding")
    if not direct_count and not candidate.unverified_suggestion:
        score = min(score, 0.52)
        candidate.risk_flags.append("no_direct_excerpt")
    if any(not item.heading_path and not item.section_title for item in evidence if item.excerpt):
        score -= 0.04
        candidate.risk_flags.append("weak_section_context")

    candidate.confidence_score = round(_clamp(score), 4)
    candidate.confidence_reasons.append(f"method reliability {candidate.evidence_method}")
    return candidate.confidence_score


def validate_candidate(candidate: TaskCandidate) -> ValidatedTask | None:
    score = candidate.confidence_score if candidate.confidence_score is not None else score_candidate(candidate)
    has_excerpt = any(item.excerpt for item in candidate.evidence_items)
    weak_or_missing = (
        candidate.unverified_suggestion
        or "keyword_only" in candidate.risk_flags
        or "missing_keyword_not_factual_finding" in candidate.risk_flags
    )

    if not has_excerpt and not candidate.unverified_suggestion:
        return None
    if score < CONFIDENCE_REVIEW_THRESHOLD and not candidate.unverified_suggestion:
        return None

    confidence_level = _confidence_level(score)
    if score >= CONFIDENCE_PROMOTION_THRESHOLD and not weak_or_missing:
        status = "needs_review"
        reason = "Evidence-backed candidate; verify scope, owner, and due date before approval."
        action = "Inspect source excerpt, then approve, assign, or dismiss."
    else:
        status = "suggested"
        confidence_level = "low" if score < 0.55 else confidence_level
        reason = "Weak or unverified signal; not a confirmed obligation, gap, or fact."
        action = "Review source context before converting this suggestion into work."

    return ValidatedTask(
        candidate=candidate,
        status=status,
        confidence_level=confidence_level,
        confidence_score=score,
        reason=reason,
        recommended_action=action,
    )


def task_validation_metadata(validated: ValidatedTask) -> dict[str, Any]:
    candidate = validated.candidate
    return {
        "task_validation": {
            "status": validated.status,
            "confidence_level": validated.confidence_level,
            "confidence_score": validated.confidence_score,
            "evidence_method": candidate.evidence_method,
            "reason": validated.reason,
            "recommended_action": validated.recommended_action,
        },
        "candidate": candidate.as_dict(),
        "evidence_items": [item.as_dict() for item in candidate.evidence_items],
        "confidence_level": validated.confidence_level,
        "confidence_score": validated.confidence_score,
        "evidence_method": candidate.evidence_method,
        "reason": validated.reason,
        "recommended_action": validated.recommended_action,
        "review_status": validated.status,
    }


def _confidence_level(score: float) -> str:
    if score >= 0.78:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
