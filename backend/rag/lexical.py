"""Lexical contract: PostgreSQL ``ts_rank_cd`` (not BM25) plus identifier hits.

Scores from ``ts_rank_cd`` stay labeled as cover-density rank. A dedicated BM25
engine is out of scope until a benchmark justifies it.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

_TOKEN_RE = re.compile(r"[^\W\s]+", flags=re.UNICODE)
_IDENTIFIER_RE = re.compile(
    r"(?:@|(?:[A-Za-z].*\d|\d.*[A-Za-z])|[-_./])",
)
_BASE64ISH_RE = re.compile(r"^[A-Za-z0-9+/=\s]{64,}$")
_EXHAUSTIVE_RE = re.compile(
    r"\b(?:list all|show all|all documents|all files|how many|number of|count)\b",
    flags=re.IGNORECASE,
)
_NAVIGATION_RE = re.compile(
    r"\b(?:find|locate|search|show|get)\b",
    flags=re.IGNORECASE,
)
_FACTUAL_RE = re.compile(
    r"\b(?:what|when|where|who|why|how much|which|define|explain|summarize)\b",
    flags=re.IGNORECASE,
)

# Keys eligible for lexical text. Internal ids, ACL blobs, and base64 stay out.
SEMANTIC_JSON_KEYS = frozenset(
    {
        "amount",
        "cc",
        "currency",
        "customer",
        "description",
        "email",
        "from",
        "identifier",
        "invoice_number",
        "name",
        "snippet",
        "subject",
        "summary",
        "title",
        "to",
        "vendor",
    }
)

LEXICAL_REGCONFIG = "simple"


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text or "") if token.strip()]


def looks_like_identifier(term: str) -> bool:
    value = (term or "").strip()
    if len(value) < 3:
        return False
    return bool(_IDENTIFIER_RE.search(value))


def semantic_json_text(value: Any, *, _depth: int = 0) -> str:
    """Allowlisted semantic fields only. Drops keys and base64-like payloads."""
    if _depth > 4 or value is None:
        return ""
    if isinstance(value, dict):
        parts: list[str] = []
        for key, item in value.items():
            if str(key) not in SEMANTIC_JSON_KEYS:
                if isinstance(item, dict):
                    nested = semantic_json_text(item, _depth=_depth + 1)
                    if nested:
                        parts.append(nested)
                continue
            rendered = semantic_json_text(item, _depth=_depth + 1)
            if rendered:
                parts.append(rendered)
        return " ".join(parts)
    if isinstance(value, list):
        return " ".join(
            semantic_json_text(item, _depth=_depth + 1) for item in value[:32]
        )
    text = str(value).strip()
    if not text or _BASE64ISH_RE.match(text):
        return ""
    return text


def classify_catalog_intent(query: str) -> str:
    """``exhaustive`` | ``navigation`` | ``factual``.

    Navigation lists files. Exhaustive catalog/count queries must not pretend a
    top-k page is the full set. Factual questions stay on retrieval.
    """
    text = query or ""
    if _EXHAUSTIVE_RE.search(text):
        return "exhaustive"
    if _FACTUAL_RE.search(text) and not _NAVIGATION_RE.search(text):
        return "factual"
    if _NAVIGATION_RE.search(text):
        return "navigation"
    return "factual"


def squash_ts_rank(rank: float) -> float:
    """Order-preserving map of ``ts_rank_cd`` into (0, 1) for the pre-RRF blend.

    This is not BM25 and not a query-local min/max.
    """
    value = max(0.0, float(rank))
    if value <= 0:
        return 0.0
    return value / (1.0 + value)


def chunk_overlap_score(terms: Sequence[str], text: str) -> float:
    """Term coverage on one text. No corpus IDF."""
    query = [term.lower() for term in terms if term]
    if not query or not text:
        return 0.0
    haystack = set(tokenize(text))
    hits = sum(1 for term in query if term.lower() in haystack or term.lower() in text.lower())
    if hits <= 0:
        return 0.0
    return hits / len(query)
