"""Conservative sentence-to-citation evidence checks."""

from __future__ import annotations

import re

from ..schemas.chat_schema import ChatSource
from .claim_values import DATE_RE, MONEY_RE, compact, money_supported

_CITATION_RE = re.compile(r"\[(?:source\s*)?(\d+)\]", re.IGNORECASE)
_ENTITY_RE = re.compile(
    r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}|[A-Z]{2,}[-_/]?[A-Z0-9-]{2,})\b"
)
_NEGATION_RE = re.compile(
    r"\b(?:no|not|never|none|without|cannot|can't|didn't|doesn't)\b", re.IGNORECASE
)
_QUALIFIER_RE = re.compile(
    r"\b(?:only|at least|at most|up to|before|after|must|may|shall|except|unless)\b",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*", re.IGNORECASE)
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "are",
        "was",
        "were",
        "have",
        "has",
        "had",
        "but",
        "your",
        "about",
        "into",
        "than",
        "then",
        "total",
        "amount",
        "source",
        "invoice",
    }
)
_GENERIC_ENTITIES = frozenset(
    {"The", "This", "That", "Invoice", "Payment", "Source", "EUR", "USD", "GBP"}
)

CheckTuple = tuple[str, str, bool]


def verify_cited_claims(answer: str, sources: list[ChatSource]) -> list[CheckTuple]:
    """Require every factual sentence/line to be supported by its own citations."""
    checks: list[CheckTuple] = []
    segments = [
        segment.strip()
        for segment in re.split(r"(?<=[.!?])\s+|\n+", answer or "")
        if segment.strip()
    ]
    for segment in segments:
        claim = _CITATION_RE.sub("", segment).strip(" \t-*•")
        if (
            not _claim_terms(claim)
            and not MONEY_RE.search(claim)
            and not DATE_RE.search(claim)
        ):
            continue
        indexes = [int(match.group(1)) for match in _CITATION_RE.finditer(segment)]
        valid = [index for index in indexes if 1 <= index <= len(sources)]
        citation_ok = bool(valid) and len(valid) == len(indexes)
        checks.append(("citation", ",".join(str(i) for i in indexes), citation_ok))
        if not citation_ok:
            continue
        cited = [sources[index - 1] for index in dict.fromkeys(valid)]
        per_source = [_source_supports_claim(claim, source) for source in cited]
        checks.extend(_structured_checks(claim, cited))
        checks.append(("span", claim[:160], any(per_source)))
    if not checks:
        return [("citation", "missing factual claim", False)]
    return checks


def _source_supports_claim(claim: str, source: ChatSource) -> bool:
    evidence = _source_text(source)
    if not evidence:
        return False
    if any(not money_supported(value, evidence) for value in MONEY_RE.findall(claim)):
        return False
    if any(compact(value) not in compact(evidence) for value in DATE_RE.findall(claim)):
        return False
    if any(compact(value) not in compact(evidence) for value in _entities(claim)):
        return False
    if _NEGATION_RE.search(claim) and not _NEGATION_RE.search(evidence):
        return False
    qualifiers = {value.lower() for value in _QUALIFIER_RE.findall(claim)}
    evidence_qualifiers = {value.lower() for value in _QUALIFIER_RE.findall(evidence)}
    if not qualifiers.issubset(evidence_qualifiers):
        return False
    claim_terms = _claim_terms(claim)
    evidence_terms = _claim_terms(evidence)
    if not claim_terms:
        return bool(MONEY_RE.search(claim) or DATE_RE.search(claim))
    overlap = claim_terms & evidence_terms
    minimum = max(1, min(3, (len(claim_terms) + 2) // 3))
    return len(overlap) >= minimum


def _structured_checks(claim: str, sources: list[ChatSource]) -> list[CheckTuple]:
    evidence = [_source_text(source) for source in sources]
    checks: list[CheckTuple] = []
    for value in MONEY_RE.findall(claim):
        checks.append(
            ("amount", value, any(money_supported(value, text) for text in evidence))
        )
    for value in DATE_RE.findall(claim):
        checks.append(
            ("date", value, any(compact(value) in compact(text) for text in evidence))
        )
    for value in _entities(claim):
        checks.append(
            (
                "entity",
                value,
                any(compact(value) in compact(text) for text in evidence),
            )
        )
    if _NEGATION_RE.search(claim):
        checks.append(
            (
                "negation",
                "explicit",
                any(_NEGATION_RE.search(text) for text in evidence),
            )
        )
    for value in dict.fromkeys(match.lower() for match in _QUALIFIER_RE.findall(claim)):
        checks.append(
            ("qualifier", value, any(value in text.lower() for text in evidence))
        )
    return checks


def _source_text(source: ChatSource) -> str:
    return " ".join(
        (source.content or "", source.snippet or "", source.section_title or "")
    )


def _claim_terms(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(text)
        if len(token) >= 3 and token.lower() not in _STOPWORDS
    }


def _entities(text: str) -> list[str]:
    return [
        value
        for value in dict.fromkeys(
            match.group(0) for match in _ENTITY_RE.finditer(text)
        )
        if value not in _GENERIC_ENTITIES
    ]
