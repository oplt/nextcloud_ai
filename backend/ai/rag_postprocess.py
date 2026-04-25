"""Reranking and context compression for retrieved sources before LLM grounding."""

from __future__ import annotations

import re

from ..schemas.chat_schema import ChatSource


def _overlap_score(question: str, source: ChatSource) -> float:
    terms = re.findall(r"[\w\-]{3,}", question.lower())
    blob = " ".join(
        [
            (source.content or source.snippet or "").lower(),
            (source.file_name or "").lower(),
            (source.section_title or "").lower(),
        ]
    )
    if not terms or not blob:
        return 0.0
    hits = sum(1 for t in terms if t in blob)
    return hits / max(len(terms), 1)


def rerank_sources_lexically(question: str, sources: list[ChatSource]) -> list[ChatSource]:
    if len(sources) <= 2:
        return sources
    scored = [(-_overlap_score(question, s) - 0.15 * s.score, i, s) for i, s in enumerate(sources)]
    scored.sort(key=lambda x: (x[0], x[1]))
    return [s for _, _, s in scored]


def compress_sources_for_prompt(
    sources: list[ChatSource],
    *,
    max_total_chars: int = 28000,
    per_source_cap: int = 9000,
) -> list[ChatSource]:
    out, _ = compress_sources_for_prompt_with_stats(
        sources, max_total_chars=max_total_chars, per_source_cap=per_source_cap
    )
    return out


def compress_sources_for_prompt_with_stats(
    sources: list[ChatSource],
    *,
    max_total_chars: int = 28000,
    per_source_cap: int = 9000,
) -> tuple[list[ChatSource], int]:
    out: list[ChatSource] = []
    truncated = 0
    budget = max_total_chars
    for source in sources:
        original = source.content or source.snippet or ""
        excerpt = original
        if len(excerpt) > per_source_cap:
            excerpt = excerpt[: per_source_cap - 1] + "…"
        if budget <= 0:
            break
        if len(excerpt) > budget:
            excerpt = excerpt[: budget - 1] + "…"
        if excerpt != original:
            truncated += 1
        budget -= len(excerpt)
        out.append(
            source.model_copy(update={"content": excerpt})
            if excerpt != original
            else source
        )
    return out, truncated


def rerank_and_truncate_sources(
    question: str,
    sources: list[ChatSource],
    *,
    stats_out: dict[str, object] | None = None,
) -> list[ChatSource]:
    before_ids = [str(s.chunk_id) for s in sources]
    ordered = rerank_sources_lexically(question, list(sources))
    lex_ids = [str(s.chunk_id) for s in ordered]
    order_changed = len(sources) > 2 and lex_ids != before_ids
    compressed, trunc_count = compress_sources_for_prompt_with_stats(ordered)
    if stats_out is not None:
        stats_out["order_changed"] = order_changed
        stats_out["sources_content_truncated"] = trunc_count
    return compressed
