"""Domain-neutral follow-up likelihood for retrieval pinning and query rewrite gating.

This module intentionally avoids business-domain terms such as employer/job/contract/etc.
It should identify whether a turn depends on previous conversation context, not what the
conversation is about. Domain-specific behavior belongs in prompt/domain profiles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Strong references that usually need prior context.
_PRONOUN_OR_DEMONSTRATIVE_RE = re.compile(
    r"\b("
    r"it|its|they|their|them|he|his|she|her|"
    r"this|that|these|those|there|here|then|"
    r"same|the same|such|above|below|previous|prior|next|"
    r"latter|former|one|ones"
    r")\b",
    re.IGNORECASE,
)

# Turn openers that often indicate ellipsis or continuation.
_CONTINUATION_OPENER_RE = re.compile(
    r"^\s*("
    r"also\b|and\b|but\b|so\b|then\b|"
    r"what about\b|how about\b|"
    r"why\b|when\b|where\b|who\b|which\b|"
    r"tell me more\b|explain\b|elaborate\b"
    r")",
    re.IGNORECASE,
)

# Polite requests are weak signals only. "Can you summarize report 2024?" can be standalone.
_POLITE_OPENER_RE = re.compile(r"^\s*(can you|could you|please)\b", re.IGNORECASE)

_RELATIVE_SEQUENCE_RE = re.compile(
    r"\b(after|before|next|previous|then|later|following|subsequent|prior|earlier)\b",
    re.IGNORECASE,
)

_CHALLENGE_RE = re.compile(
    r"\b("
    r"wrong answer|wrong|incorrect|not correct|not accurate|are you sure|sure\?|"
    r"that is wrong|that's wrong|that is incorrect|recheck|check again|verify again"
    r")\b",
    re.IGNORECASE,
)

_QUOTED_TEXT_RE = re.compile(r"['\"“”‘’].{3,}['\"“”‘’]")


@dataclass(slots=True)
class FollowUpClassification:
    is_follow_up: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)


def _tokenize(question: str) -> list[str]:
    return re.findall(r"\w+", question)


def has_contextual_reference(question: str) -> bool:
    """Return True when the text contains generic references to prior context."""
    return bool(
        _PRONOUN_OR_DEMONSTRATIVE_RE.search(question)
        or _CONTINUATION_OPENER_RE.search(question)
        or _RELATIVE_SEQUENCE_RE.search(question)
    )


def is_challenge_turn(question: str) -> bool:
    """Return True when the user is challenging or asking to re-check prior output."""
    return bool(_CHALLENGE_RE.search(question))


def classify_follow_up(question: str, *, has_history: bool) -> FollowUpClassification:
    """Classify whether a user turn needs conversation history for retrieval.

    The classifier is intentionally heuristic and conservative. It should prefer false
    negatives over false positives for long/self-contained questions, because unnecessary
    rewriting can pollute retrieval with stale conversation context.
    """
    reasons: list[str] = []
    if not has_history:
        return FollowUpClassification(False, 0.0, reasons)

    normalized = " ".join(question.split())
    if not normalized:
        return FollowUpClassification(False, 0.0, reasons)

    words = _tokenize(normalized)
    word_count = len(words)
    score = 0.0

    if _CHALLENGE_RE.search(normalized):
        score += 0.55
        reasons.append("challenge_turn")

    if _PRONOUN_OR_DEMONSTRATIVE_RE.search(normalized):
        score += 0.34
        reasons.append("contextual_reference")

    if _CONTINUATION_OPENER_RE.search(normalized):
        score += 0.30
        reasons.append("continuation_opener")

    if _RELATIVE_SEQUENCE_RE.search(normalized):
        score += 0.24
        reasons.append("relative_sequence")

    if _POLITE_OPENER_RE.search(normalized):
        score += 0.10
        reasons.append("polite_opener_weak")

    if word_count <= 4:
        score += 0.28
        reasons.append("very_short_turn")
    elif word_count <= 10:
        score += 0.10
        reasons.append("short_turn")

    # Long, explicit, quoted, or identifier-heavy questions are often standalone even if
    # they start with a polite phrase or contain words like "this" in a quoted title.
    if word_count >= 14:
        score -= 0.20
        reasons.append("long_question_penalty")
    if _QUOTED_TEXT_RE.search(normalized):
        score -= 0.12
        reasons.append("quoted_text_penalty")
    if any(ch.isdigit() for ch in normalized) and word_count >= 8:
        score -= 0.08
        reasons.append("self_contained_digits_penalty")
    if any(len(w) > 18 for w in words):
        score -= 0.12
        reasons.append("long_identifier_penalty")

    confidence = max(0.0, min(1.0, score))
    is_follow_up = confidence >= 0.46
    return FollowUpClassification(is_follow_up=is_follow_up, confidence=confidence, reasons=reasons)