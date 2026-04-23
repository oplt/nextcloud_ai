"""Structured follow-up likelihood for retrieval pinning and query rewrite gating."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_FOLLOW_UP_RE = re.compile(
    r"^\s*("
    r"it\b|its\b|they\b|their\b|them\b|"
    r"this\b|that\b|these\b|those\b|"
    r"the same\b|"
    r"also\b|and\b|but\b|"
    r"what about\b|how about\b|"
    r"why\b|when\b|where\b|who\b|which\b|"
    r"tell me more|explain|elaborate|"
    r"can you|could you|please\b"
    r")",
    re.IGNORECASE,
)


@dataclass(slots=True)
class FollowUpClassification:
    is_follow_up: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)


def classify_follow_up(question: str, *, has_history: bool) -> FollowUpClassification:
    reasons: list[str] = []
    if not has_history:
        return FollowUpClassification(False, 0.0, reasons)

    words = question.split()
    score = 0.0
    if _FOLLOW_UP_RE.search(question):
        score += 0.38
        reasons.append("follow_up_opener")
    if len(words) <= 4:
        score += 0.28
        reasons.append("very_short_turn")
    elif len(words) <= 10:
        score += 0.12
        reasons.append("short_turn")
    if any(len(w) > 14 for w in words):
        score -= 0.18
        reasons.append("long_named_entity_penalty")
    if any(ch.isdigit() for ch in question) and len(words) >= 6:
        score += 0.08
        reasons.append("has_digits")

    confidence = max(0.0, min(1.0, score))
    is_follow_up = confidence >= 0.46
    return FollowUpClassification(is_follow_up=is_follow_up, confidence=confidence, reasons=reasons)
