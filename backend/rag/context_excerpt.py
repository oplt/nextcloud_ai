"""Structure-preserving excerpt selection for prompt evidence."""

from __future__ import annotations

import re

_CODE_OR_ROW_RE = re.compile(r"(^\s{2,}|^\t|\||```)", flags=re.MULTILINE)


def preserve_structure_excerpt(text: str, *, question: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text

    if _CODE_OR_ROW_RE.search(text):
        lines = text.splitlines()
        kept: list[str] = []
        size = 0
        for line in lines:
            if (
                not kept
                or _CODE_OR_ROW_RE.search(line)
                or any(term in line.lower() for term in _query_terms(question)[:8])
            ):
                addition = len(line) + 1
                if size + addition > max_chars:
                    break
                kept.append(line)
                size += addition
        if kept:
            excerpt = "\n".join(kept)
            if len(excerpt) < len(text):
                return excerpt.rstrip() + "…"
            return excerpt

    terms = _query_terms(question)
    lowered = text.lower()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    if not positions:
        return text[: max_chars - 1].rstrip() + "…"
    center = min(positions)
    half = max_chars // 2
    start = max(0, center - half)
    end = min(len(text), start + max_chars)
    start = max(0, end - max_chars)
    excerpt = text[start:end]
    if start > 0:
        excerpt = "…" + excerpt[1:]
    if end < len(text):
        excerpt = excerpt[:-1] + "…"
    return excerpt


def _query_terms(question: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"[\w\-]{3,}", (question or "").lower())))
