from __future__ import annotations

import re

from ..db.models import DocumentChunk
from .stores import RetrievalCandidate

_TOKEN_RE = re.compile(r"[^\W\s]+", flags=re.UNICODE)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_YEAR_RANGE_RE = re.compile(
    r"\b((?:19|20)\d{2})\b.{0,48}?(?:-|to|through|until|–|—).{0,48}?\b((?:19|20)\d{2}|present|current|now)\b",
    flags=re.IGNORECASE,
)
_AMOUNT_QUERY_TERMS = {
    "amount",
    "total",
    "balance",
    "due",
    "pay",
    "payable",
    "paid",
    "cost",
    "price",
    "invoice",
    "factuur",
    "bill",
    "charge",
}
_MONEY_RE = re.compile(
    r"(?:€\s*\d[\d.,]*|\d[\d.,]*\s*(?:eur|euro|€))",
    flags=re.IGNORECASE,
)
_AMOUNT_CONTEXT_RE = re.compile(
    r"\b(total|amount|balance|due|payable|pay|invoice|factuur|bill|charge|incl|btw|vat|te betalen|bedrag)\b",
    flags=re.IGNORECASE,
)
_DUE_DATE_QUERY_TERMS = {"due", "deadline", "payment", "pay", "payable", "vervaldatum"}
_DUE_DATE_CONTEXT_RE = re.compile(
    r"\b(te betalen voor|vervaldatum|due date|pay before|pay by|payment due|aan bij uw bankinstelling)\b",
    flags=re.IGNORECASE,
)



class ContextReranker:
    def __init__(
            self,
            *,
            vector_weight: float = 0.45,
            keyword_weight: float = 0.35,
            content_weight: float = 0.20,
    ) -> None:
        self.vector_weight = max(0.0, min(1.0, vector_weight))
        self.keyword_weight = max(0.0, min(1.0, keyword_weight))
        self.content_weight = max(0.0, min(1.0, content_weight))

    def rerank(
            self,
            *,
            question: str,
            keyword_terms: list[str],
            candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        question_terms = _terms(question)
        all_terms = _dedupe([*keyword_terms, *question_terms])

        for candidate in candidates:
            candidate.fused_score = self._weighted_fusion(candidate)
            candidate.rerank_score = self._score(
                question_terms=question_terms,
                keyword_terms=all_terms,
                candidate=candidate,
            )

        return sorted(candidates, key=lambda item: item.score, reverse=True)

    def _score(
            self,
            *,
            question_terms: list[str],
            keyword_terms: list[str],
            candidate: RetrievalCandidate,
    ) -> float:
        chunk = candidate.chunk

        score = (
                candidate.semantic_score * self.vector_weight
                + candidate.keyword_score * self.keyword_weight
                + self._content_score(question_terms, keyword_terms, chunk) * self.content_weight
        )

        total_weight = (
                self.vector_weight
                + self.keyword_weight
                + self.content_weight
        )

        if total_weight <= 0:
            return self._fallback_score(candidate)

        normalized = score / total_weight
        normalized += self._temporal_score(question_terms, chunk)
        normalized += self._structured_row_score(question_terms, chunk)
        normalized += self._money_score(question_terms, chunk)
        normalized += self._due_date_score(question_terms, chunk)
        return min(0.999, max(0.0, normalized))

    def _weighted_fusion(self, candidate: RetrievalCandidate) -> float:
        total_weight = self.vector_weight + self.keyword_weight
        if total_weight <= 0:
            return max(candidate.semantic_score, candidate.keyword_score)

        return min(
            0.999,
            max(
                0.0,
                (
                        candidate.semantic_score * self.vector_weight
                        + candidate.keyword_score * self.keyword_weight
                )
                / total_weight,
                ),
        )

    @staticmethod
    def _content_score(
            question_terms: list[str],
            keyword_terms: list[str],
            chunk: DocumentChunk,
    ) -> float:
        terms = _dedupe([*question_terms, *keyword_terms])
        if not terms:
            return 0.0

        document = chunk.document
        weighted_fields = [
            (chunk.content or "", 1.0),
            (chunk.section_title or "", 1.5),
            (chunk.heading_path or "", 1.5),
            ((document.file_name if document is not None else "") or "", 2.5),
            ((document.file_path if document is not None else "") or "", 2.0),
            ((document.document_type if document is not None else "") or "", 2.0),
            ((document.business_domain if document is not None else "") or "", 2.0),
            (_json_text(document.metadata_json) if document is not None else "", 2.5),
            (_json_text(document.extracted_fields_json) if document is not None else "", 3.0),
        ]

        score = 0.0
        max_field_weight = max(weight for _, weight in weighted_fields)

        for term in terms:
            lowered = term.lower()
            term_score = 0.0
            for value, weight in weighted_fields:
                if lowered in value.lower():
                    term_score = max(term_score, weight)
            score += term_score / max_field_weight

        return min(1.0, score / max(len(terms), 1))

    def _fallback_score(self, candidate: RetrievalCandidate) -> float:
        return self._weighted_fusion(candidate)

    @staticmethod
    def _temporal_score(question_terms: list[str], chunk: DocumentChunk) -> float:
        requested_years = [
            int(term)
            for term in question_terms
            if _YEAR_RE.fullmatch(term)
        ]
        if not requested_years:
            return 0.0
        text = _chunk_search_text(chunk)
        if not text:
            return 0.0
        exact_years = {int(match.group(0)) for match in _YEAR_RE.finditer(text)}
        ranges = []
        for match in _YEAR_RANGE_RE.finditer(text):
            start = int(match.group(1))
            end_raw = match.group(2).lower()
            end = 9999 if end_raw in {"present", "current", "now"} else int(end_raw)
            if end < start:
                start, end = end, start
            ranges.append((start, end))
        if all(
            year in exact_years or any(start <= year <= end for start, end in ranges)
            for year in requested_years
        ):
            return 0.35
        return 0.0

    @staticmethod
    def _structured_row_score(question_terms: list[str], chunk: DocumentChunk) -> float:
        if not question_terms:
            return 0.0
        text = _chunk_search_text(chunk)
        if "|" not in text:
            return 0.0
        matched_terms = sum(1 for term in set(question_terms) if term in text.lower())
        return min(0.2, matched_terms * 0.05)

    @staticmethod
    def _money_score(question_terms: list[str], chunk: DocumentChunk) -> float:
        if not _AMOUNT_QUERY_TERMS.intersection(question_terms):
            return 0.0
        text = _chunk_search_text(chunk)
        if not _MONEY_RE.search(text):
            return 0.0
        score = 0.25
        if _AMOUNT_CONTEXT_RE.search(text):
            score += 0.2
        return score

    @staticmethod
    def _due_date_score(question_terms: list[str], chunk: DocumentChunk) -> float:
        if not _DUE_DATE_QUERY_TERMS.intersection(question_terms):
            return 0.0
        text = _chunk_search_text(chunk)
        if not re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text):
            return 0.0
        return 0.45 if _DUE_DATE_CONTEXT_RE.search(text) else 0.0

def _terms(text: str) -> list[str]:
    return [
        token.lower()
        for token in _TOKEN_RE.findall(text or "")
        if len(token) > 1 or any(ch.isdigit() for ch in token)
    ]


def _dedupe(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        normalized = term.lower().strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _chunk_search_text(chunk: DocumentChunk) -> str:
    document = chunk.document
    return " ".join(
        [
            chunk.content or "",
            chunk.section_title or "",
            chunk.heading_path or "",
            (document.file_name if document is not None else "") or "",
            (document.file_path if document is not None else "") or "",
        ]
    )


def _json_text(value: dict | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for key, item in value.items():
        parts.append(str(key))
        if isinstance(item, dict):
            parts.append(_json_text(item))
        elif isinstance(item, list):
            parts.extend(str(entry) for entry in item)
        elif item is not None:
            parts.append(str(item))
    return " ".join(parts)
