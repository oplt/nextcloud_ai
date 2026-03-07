from __future__ import annotations

import re

# Compiled once at import — avoids recompilation on every build_snippet call.
_WS_RE = re.compile(r"\s+")


def build_snippet(text: str, *, limit: int = 280) -> str:
    cleaned = _WS_RE.sub(" ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def distance_to_score(distance: float) -> float:
    """
    Convert cosine distance to a rough 0..1 similarity score.

    cosine distance:
      0   -> identical
      1   -> orthogonal
      2   -> opposite
    """
    return max(0.0, min(1.0, 1.0 - distance * 0.5))