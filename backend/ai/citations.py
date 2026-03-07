from __future__ import annotations

import re

_WS_RE = re.compile(r"\s+")


def build_snippet(text: str, *, limit: int = 280) -> str:
    cleaned = _WS_RE.sub(" ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def distance_to_score(distance: float) -> float:
    return max(0.0, min(1.0, 1.0 - distance * 0.5))
