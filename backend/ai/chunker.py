from __future__ import annotations

import re

# Compiled once at import time — reused on every call.
_WORD_RE = re.compile(r"\S+")


def chunk_text(
        text: str,
        chunk_size: int = 800,
        overlap: int = 120,
) -> list[str]:
    if overlap >= chunk_size:
        raise ValueError(
            f"overlap ({overlap}) must be less than chunk_size ({chunk_size}), "
            "otherwise the window never advances."
        )

    # Record (start, end) char offsets for every word — no list of strings created.
    spans = [(m.start(), m.end()) for m in _WORD_RE.finditer(text)]
    n = len(spans)
    if not n:
        return []

    step = chunk_size - overlap
    chunks: list[str] = []

    # Slice directly from the original string instead of re-joining words.
    for start in range(0, n, step):
        end = min(start + chunk_size, n)
        # text[first_word_start : last_word_end] preserves original spacing inline.
        chunks.append(text[spans[start][0] : spans[end - 1][1]])

    return chunks