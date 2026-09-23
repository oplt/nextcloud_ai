"""Citation validity and claim-support checks for grounded answers.

Does not attach citations merely because some source exists. Unsupported
structured claims (amount/currency/date/entity) cause abstention or correction
from evidence; general claims need conservative span overlap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..ai.citations import build_snippet
from ..schemas.chat_schema import ChatSource
from .claim_support import verify_cited_claims

_CITATION_RE = re.compile(r"\[(?:source\s*)?(\d+)\]", flags=re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_YEAR_RANGE_RE = re.compile(
    r"\b((?:19|20)\d{2})\b.{0,48}?(?:-|to|through|until|–|—).{0,48}?\b((?:19|20)\d{2}|present|current|now)\b",
    flags=re.IGNORECASE,
)
_MONEY_RE = re.compile(
    r"(?:"
    r"€\s*\d[\d.,]*"
    r"|\d[\d.,]*\s*(?:eur|euro|€|usd|gbp|\$)"
    r"|(?:eur|usd|gbp|\$)\s*\d[\d.,]*"
    r")",
    flags=re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b",
    flags=re.IGNORECASE,
)
_ENTITY_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}|[A-Z]{2,}[-_/]?[A-Z0-9]{2,})\b"
)
_EVIDENCE_STOPWORDS = frozenset(
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
        "not",
        "but",
        "you",
        "your",
        "about",
        "into",
        "than",
        "then",
        "total",
        "amount",
    }
)

UNVERIFIED_ANSWER = "I could not verify that from the indexed sources."
INSUFFICIENT_ANSWER_MARKERS = (
    "could not verify",
    "insufficient",
    "not enough indexed",
)


@dataclass(slots=True)
class ClaimCheck:
    kind: str
    value: str
    supported: bool


@dataclass(slots=True)
class EvidenceVerification:
    answer: str
    sources: list[ChatSource]
    result: str
    support_check_passed: bool = False
    claim_checks: list[ClaimCheck] = field(default_factory=list)
    details: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        payload = {
            "result": self.result,
            "support_check_passed": self.support_check_passed,
            "claim_checks": [
                {"kind": item.kind, "value": item.value, "supported": item.supported}
                for item in self.claim_checks
            ],
        }
        payload.update(self.details)
        return payload


def filter_sources_to_citations(
    answer: str, sources: list[ChatSource]
) -> tuple[str, list[ChatSource]]:
    """Keep only cited indexes; remap ``[n]`` to dense 1..k. Drop invalid cites."""
    if not sources:
        return answer, []

    cited_indexes: list[int] = []
    seen: set[int] = set()
    for match in _CITATION_RE.finditer(answer):
        source_index = int(match.group(1))
        if source_index < 1 or source_index > len(sources):
            continue
        if source_index in seen:
            continue
        seen.add(source_index)
        cited_indexes.append(source_index)

    if not cited_indexes:
        return answer, []

    remapped = {original: new for new, original in enumerate(cited_indexes, start=1)}
    filtered = [sources[idx - 1] for idx in cited_indexes]
    normalized = _CITATION_RE.sub(
        lambda m: (
            f"[{remapped[int(m.group(1))]}]" if int(m.group(1)) in remapped else ""
        ),
        answer,
    )
    normalized = re.sub(r"\s{2,}", " ", normalized).strip()
    return normalized, filtered


def select_supporting_sources(
    *,
    question: str,
    answer: str,
    sources: list[ChatSource],
    max_sources: int = 2,
) -> list[ChatSource]:
    candidates = [
        source for source in sources if (source.content or source.snippet or "").strip()
    ]
    years = requested_years(question)
    if years:
        candidates = [s for s in candidates if source_supports_years(s, years)]
        if not candidates:
            return []

    scored: list[tuple[int, ChatSource]] = []
    answer_terms = evidence_terms(answer)
    markers = extract_claim_markers(answer)
    for source in candidates:
        if not source_supports_answer_text(answer=answer, source=source):
            continue
        source_terms = evidence_terms(source.content or source.snippet or "")
        score = len(answer_terms & source_terms)
        if markers:
            compact = re.sub(
                r"\s+", "", (source.content or source.snippet or "").lower()
            )
            score += 5 * sum(1 for marker in markers if marker in compact)
        scored.append((score, source))
    if not scored:
        return []
    scored.sort(key=lambda item: item[0], reverse=True)
    return [source for _, source in scored[:max_sources]]


def answer_is_supported(
    *,
    question: str,
    answer: str,
    cited_sources: list[ChatSource],
) -> tuple[bool, list[ClaimCheck]]:
    checks: list[ClaimCheck] = []
    if not cited_sources:
        return False, checks
    if is_insufficient_answer(answer):
        return True, checks

    years = requested_years(question)
    if years:
        years_ok = any(source_supports_years(source, years) for source in cited_sources)
        checks.append(
            ClaimCheck(
                kind="year",
                value=",".join(str(year) for year in years),
                supported=years_ok,
            )
        )
        if not years_ok:
            return False, checks

    checks.extend(
        ClaimCheck(kind=kind, value=value, supported=supported)
        for kind, value, supported in verify_cited_claims(answer, cited_sources)
    )
    return all(check.supported for check in checks), checks


def verify_and_normalize_answer(
    *,
    question: str,
    answer: str,
    sources: list[ChatSource],
    shadow_mode: bool = False,
    strip_question_echo: bool = True,
) -> EvidenceVerification:
    details: dict[str, object] = {"shadow_mode": shadow_mode}
    working = answer.strip()
    if strip_question_echo:
        working = strip_leading_question_echo(question=question, answer=working)

    citation_indexes = [int(match.group(1)) for match in _CITATION_RE.finditer(working)]
    invalid_citations = [
        index for index in citation_indexes if index < 1 or index > len(sources)
    ]
    if invalid_citations:
        strict = unverified_answer(question)
        details.update(
            {
                "invalid_citation_ids": invalid_citations,
                "strict_answer_would_be": strict,
            }
        )
        if shadow_mode:
            details["shadow_kept_raw"] = True
            return EvidenceVerification(
                answer=working,
                sources=[],
                result="invalid_citations",
                details=details,
            )
        return EvidenceVerification(
            answer=strict,
            sources=[],
            result="invalid_citations",
            details=details,
        )

    normalized, cited = filter_sources_to_citations(working, sources)

    if is_insufficient_answer(normalized):
        return EvidenceVerification(
            answer=normalized,
            sources=cited,
            result="insufficient_answer",
            support_check_passed=True,
            details=details,
        )

    if not cited:
        strict = unverified_answer(question)
        details["strict_answer_would_be"] = strict
        if shadow_mode:
            details["shadow_kept_raw"] = True
            return EvidenceVerification(
                answer=answer.strip(),
                sources=[],
                result="no_inline_citations",
                details=details,
            )
        return EvidenceVerification(
            answer=strict,
            sources=[],
            result="no_inline_citations",
            details=details,
        )

    ok, checks = answer_is_supported(
        question=question, answer=normalized, cited_sources=cited
    )
    if not ok:
        strict = unverified_answer(question)
        details["strict_answer_would_be"] = strict
        if shadow_mode:
            details["shadow_keeps_citation_answer"] = True
            return EvidenceVerification(
                answer=normalized,
                sources=cited,
                result="support_check_failed",
                support_check_passed=False,
                claim_checks=checks,
                details=details,
            )
        return EvidenceVerification(
            answer=strict,
            sources=[],
            result="support_check_failed",
            support_check_passed=False,
            claim_checks=checks,
            details=details,
        )

    return EvidenceVerification(
        answer=normalized,
        sources=cited,
        result="passed",
        support_check_passed=True,
        claim_checks=checks,
        details=details,
    )


def build_extractive_fallback(
    sources: list[ChatSource],
    *,
    mode: str = "extractive_llm_outage",
    limit: int = 2,
) -> tuple[str, list[ChatSource], str]:
    """Simple extractive answer when generation fails. Records ``mode``."""
    if not sources:
        return (
            "I could not answer because the language model request failed. "
            "Your question was saved in the chat history.",
            [],
            mode,
        )
    chosen = sources[:limit]
    bits: list[str] = []
    for index, source in enumerate(chosen, start=1):
        text = (source.content or source.snippet or "").strip()
        if not text:
            continue
        bits.append(f"{build_snippet(text, limit=280)} [{index}]")
    if not bits:
        return (
            "I found source material, but could not summarize it because generation failed.",
            chosen,
            mode,
        )
    return (
        "I found relevant indexed source material: " + " ".join(bits),
        chosen,
        mode,
    )


def append_citations(answer: str, count: int) -> str:
    trimmed = answer.strip()
    if not trimmed or count <= 0:
        return trimmed
    suffix = "".join(f"[{index}]" for index in range(1, count + 1))
    return f"{trimmed} {suffix}"


def unverified_answer(question: str) -> str:
    lowered = question.lower()
    if any(token in lowered for token in ("wrong", "incorrect", "false", "sure")):
        return "I could not verify that claim from the indexed sources."
    return UNVERIFIED_ANSWER


def is_insufficient_answer(answer: str) -> bool:
    lowered = (answer or "").lower()
    return any(marker in lowered for marker in INSUFFICIENT_ANSWER_MARKERS)


def requested_years(question: str) -> list[int]:
    years: list[int] = []
    seen: set[int] = set()
    for match in _YEAR_RE.finditer(question or ""):
        year = int(match.group(0))
        if year in seen:
            continue
        seen.add(year)
        years.append(year)
    return years


def source_supports_years(source: ChatSource, years: list[int]) -> bool:
    if not years:
        return True
    text = " ".join(
        [
            source.content or "",
            source.snippet or "",
            source.file_name or "",
            source.file_path or "",
            source.section_title or "",
            source.heading_path or "",
        ]
    ).lower()
    if not text:
        return False
    exact = {int(m.group(0)) for m in _YEAR_RE.finditer(text)}
    ranges: list[tuple[int, int]] = []
    for match in _YEAR_RANGE_RE.finditer(text):
        start = int(match.group(1))
        end_raw = match.group(2).lower()
        end = 9999 if end_raw in {"present", "current", "now"} else int(end_raw)
        if end < start:
            start, end = end, start
        ranges.append((start, end))
    for year in years:
        if year in exact:
            continue
        if any(start <= year <= end for start, end in ranges):
            continue
        return False
    return True


def structured_claims(answer: str) -> list[tuple[str, str]]:
    claims: list[tuple[str, str]] = []
    for match in _MONEY_RE.finditer(answer or ""):
        claims.append(("amount", _normalize_money(match.group(0))))
    for match in _DATE_RE.finditer(answer or ""):
        claims.append(("date", match.group(0).lower()))
    for match in _ENTITY_RE.finditer(answer or ""):
        value = match.group(1).strip()
        if len(value) < 3 or value.lower() in _EVIDENCE_STOPWORDS:
            continue
        # Skip pure years already covered.
        if _YEAR_RE.fullmatch(value):
            continue
        claims.append(("entity", value))
    # Deduplicate while preserving order.
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for item in claims:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique[:12]


def extract_claim_markers(text: str) -> set[str]:
    markers: set[str] = set()
    for kind, value in structured_claims(text):
        if kind == "amount":
            markers.add(value)
        else:
            markers.add(re.sub(r"\s+", "", value.lower()))
    for match in re.finditer(
        r"\b(?:inv|invoice)[- ]?[a-z0-9\-./]+\b", (text or "").lower()
    ):
        markers.add(re.sub(r"\s+", "", match.group(0)))
    for match in re.finditer(r"\b\d{4,}\b", text or ""):
        markers.add(match.group(0))
    return markers


def claim_in_source(value: str, source: ChatSource) -> bool:
    blob = " ".join(
        [
            source.content or "",
            source.snippet or "",
            source.file_name or "",
            source.section_title or "",
        ]
    )
    compact_blob = re.sub(r"\s+", "", blob.lower())
    compact_value = re.sub(r"\s+", "", value.lower())
    if compact_value and compact_value in compact_blob:
        return True
    # Amount: compare digit sequences so "€1.234,56" ≈ "1234,56".
    digits_value = re.sub(r"[^\d]", "", value)
    digits_blob = re.sub(r"[^\d]", "", blob)
    if len(digits_value) >= 3 and digits_value in digits_blob:
        return True
    return value.lower() in blob.lower()


def source_supports_answer_text(*, answer: str, source: ChatSource) -> bool:
    source_text = f" {(source.content or source.snippet or '').lower()} "
    if not source_text.strip():
        return False
    markers = extract_claim_markers(answer)
    if markers:
        compact_source = re.sub(r"\s+", "", source_text)
        if not any(
            marker in compact_source or marker in source_text for marker in markers
        ):
            return False
    answer_terms = evidence_terms(answer)
    if not answer_terms:
        return False
    source_terms = evidence_terms(source_text)
    if not source_terms:
        return False
    overlap = answer_terms & source_terms
    min_hits = 1 if markers else max(2, (len(answer_terms) + 2) // 3)
    return len(overlap) >= min_hits


def evidence_terms(text: str) -> set[str]:
    tokens = {
        token.lower()
        for token in re.findall(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*", (text or "").lower())
        if token
    }
    return {
        token
        for token in tokens
        if len(token) >= 3 and token not in _EVIDENCE_STOPWORDS
    }


def strip_leading_question_echo(*, question: str, answer: str) -> str:
    trimmed = (answer or "").strip()
    q = (question or "").strip()
    if not trimmed or not q:
        return trimmed
    if trimmed.lower().startswith(q.lower()):
        return trimmed[len(q) :].lstrip(" \n:-")
    return trimmed


def _normalize_money(value: str) -> str:
    return re.sub(r"\s+", "", value.lower())
