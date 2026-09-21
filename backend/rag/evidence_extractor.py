"""Domain-neutral evidence extraction primitives for direct RAG answers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..schemas.chat_schema import ChatSource

_MONEY_RE = re.compile(
    r"(?:"
    r"€\s*\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{1,2})?"
    r"|\d{1,3}(?:[.,\s]\d{3})*[.,]\d{2}\s*(?:eur|euro|€)"
    r"|\b(?:eur|euro)\s*\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{1,2})?"
    r")",
    flags=re.IGNORECASE,
)
_AMOUNT_CONTEXT_RE = re.compile(
    r"\b(total|amount|balance|due|payable|pay|invoice|factuur|bill|charge|incl|btw|vat|te betalen|bedrag)\b",
    flags=re.IGNORECASE,
)
_YEAR_RANGE_RE = re.compile(
    r"\b((?:19|20)\d{2})\b.{0,48}?(?:-|to|through|until|–|—).{0,48}?\b((?:19|20)\d{2}|present|current|now)\b",
    flags=re.IGNORECASE,
)
_PIPE_RANGE_ROW_RE = re.compile(
    r"(?P<label>[^|\n]{2,120}?)\s*\|\s*(?P<context>[^|\n]{2,100}?)\s*\|\s*(?P<start>(?:[A-Z][a-z]{2,8}\s+)?(?:19|20)\d{2})\s*[-–—]\s*(?P<end>(?:(?:[A-Z][a-z]{2,8}\s+)?(?:19|20)\d{2})|present|current|now)",
    flags=re.IGNORECASE,
)
_START_MARKER_RE = re.compile(
    r"\b(?:since|from|started|start(?:ed)?\s+(?:in|on)?|joined|join(?:ed)?\s+(?:in|on)?|began|begin(?:s)?\s+(?:in|on)?)\b",
    flags=re.IGNORECASE,
)

# Re-exported for ChatService answer builders that share the same patterns.
MONEY_RE = _MONEY_RE
AMOUNT_CONTEXT_RE = _AMOUNT_CONTEXT_RE
YEAR_RANGE_RE = _YEAR_RANGE_RE
PIPE_RANGE_ROW_RE = _PIPE_RANGE_ROW_RE
START_MARKER_RE = _START_MARKER_RE


@dataclass(slots=True)
class EvidenceMatch:
    """Reusable direct-evidence match used before grounded generation."""

    kind: str
    value: str
    source: ChatSource
    score: float
    label: str = ""
    context: str = ""
    start: str = ""
    end: str = ""


class EvidenceExtractor:
    """Small, domain-neutral extraction primitives for common RAG answers.

    These methods intentionally extract evidence shapes, not business-domain answers.
    Domain answer builders can combine them with question intent and source scoring.
    """

    @staticmethod
    def source_text(source: ChatSource) -> str:
        return " ".join(
            part
            for part in [
                source.content or "",
                source.snippet or "",
                source.section_title or "",
                source.heading_path or "",
                source.file_name or "",
                source.file_path or "",
            ]
            if part
        )

    @staticmethod
    def lines(source: ChatSource) -> list[str]:
        text = "\n".join(
            part
            for part in [
                source.content or "",
                source.snippet or "",
                source.section_title or "",
                source.heading_path or "",
            ]
            if part
        )
        out: list[str] = []
        for raw_line in text.splitlines():
            line = " ".join(raw_line.split()).strip()
            if line:
                out.append(line)
        if not out and text.strip():
            out.append(" ".join(text.split()))
        return out

    @staticmethod
    def normalize_entity_terms(terms: list[str]) -> list[str]:
        return [re.sub(r"[^a-z0-9]+", "", term.lower()) for term in terms if term]

    @classmethod
    def entity_match_score(cls, entity_terms: list[str], text: str) -> float:
        if not entity_terms:
            return 0.0
        normalized_text = re.sub(r"[^a-z0-9]+", "", text.lower())
        score = 0.0
        for term in cls.normalize_entity_terms(entity_terms):
            if not term:
                continue
            if term in normalized_text:
                score += 1.0
            elif len(term) >= 6 and term[:6] in normalized_text:
                score += 0.7
        return score

    @classmethod
    def date_range_extractor(cls, sources: list[ChatSource]) -> list[EvidenceMatch]:
        matches: list[EvidenceMatch] = []
        for source in sources:
            for line in cls.lines(source):
                for match in _PIPE_RANGE_ROW_RE.finditer(line):
                    label = " ".join(match.group("label").split()).strip(":- ")
                    context = " ".join(match.group("context").split()).strip(":- ")
                    start = match.group("start").strip()
                    end = match.group("end").strip()
                    matches.append(
                        EvidenceMatch(
                            kind="date_range",
                            value=f"{start} - {end}",
                            source=source,
                            score=source.score + 0.30,
                            label=label,
                            context=context,
                            start=start,
                            end=end,
                        )
                    )
                for match in _YEAR_RANGE_RE.finditer(line):
                    start = match.group(1).strip()
                    end = match.group(2).strip()
                    context_start = max(0, match.start() - 120)
                    context_end = min(len(line), match.end() + 120)
                    context = " ".join(line[context_start:context_end].split()).strip(
                        ":- "
                    )
                    matches.append(
                        EvidenceMatch(
                            kind="date_range",
                            value=f"{start} - {end}",
                            source=source,
                            score=source.score + 0.15,
                            label=context,
                            context=context,
                            start=start,
                            end=end,
                        )
                    )
        return matches

    @classmethod
    def amount_extractor(
        cls, sources: list[ChatSource], *, entity_terms: list[str] | None = None
    ) -> list[EvidenceMatch]:
        matches: list[EvidenceMatch] = []
        terms = entity_terms or []
        for source in sources:
            text = cls.source_text(source)
            entity_score = cls.entity_match_score(terms, text)
            if terms and entity_score <= 0:
                continue
            for match in _MONEY_RE.finditer(text):
                amount = " ".join(match.group(0).replace("€", " EUR").split())
                if amount.lower().startswith("eur"):
                    amount = amount[3:].strip() + " EUR"
                start = max(0, match.start() - 90)
                end = min(len(text), match.end() + 90)
                context = text[start:end]
                score = source.score + entity_score * 5.0
                if _AMOUNT_CONTEXT_RE.search(context):
                    score += 3.0
                if re.search(
                    r"\b(te betalen|payable|total|invoice total|factuur.*bedrag|bedrag)\b",
                    context,
                    re.I,
                ):
                    score += 4.0
                matches.append(
                    EvidenceMatch(
                        kind="amount",
                        value=amount,
                        source=source,
                        score=score,
                        context=context,
                    )
                )
        return sorted(matches, key=lambda item: item.score, reverse=True)

    @classmethod
    def entity_proximity_extractor(
        cls,
        sources: list[ChatSource],
        *,
        entity_terms: list[str],
        value_pattern: re.Pattern[str],
        context_window: int = 180,
        require_start_marker: bool = False,
    ) -> list[EvidenceMatch]:
        matches: list[EvidenceMatch] = []
        compact_terms = cls.normalize_entity_terms(entity_terms)
        if not compact_terms:
            return matches
        for source in sources:
            text = cls.source_text(source)
            compact_text = re.sub(r"[^a-z0-9]+", "", text.lower())
            if not any(term and term in compact_text for term in compact_terms):
                continue
            for value_match in value_pattern.finditer(text):
                start = max(0, value_match.start() - context_window)
                end = min(len(text), value_match.end() + context_window)
                context = text[start:end]
                entity_score = cls.entity_match_score(entity_terms, context)
                if entity_score <= 0:
                    continue
                if require_start_marker and not _START_MARKER_RE.search(context):
                    continue
                score = source.score + entity_score * 4.0
                if _START_MARKER_RE.search(context):
                    score += 3.0
                matches.append(
                    EvidenceMatch(
                        kind="entity_proximity",
                        value=value_match.group(0),
                        source=source,
                        score=score,
                        context=" ".join(context.split()),
                    )
                )
        return sorted(matches, key=lambda item: item.score, reverse=True)
