"""Token-aware evidence packing for grounded generation prompts.

Citation IDs are assigned only after the final pack so ``[1]`` always maps to
the first packed source. Expansion/dedupe must finish before calling this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..schemas.chat_schema import ChatSource
from .answer import build_source_block

# Approximate tokenizer: ~4 characters per token for Latin text.
_CHARS_PER_TOKEN = 4.0
_CODE_OR_ROW_RE = re.compile(r"(^\s{2,}|^\t|\||```)", flags=re.MULTILINE)


@dataclass(slots=True)
class PackedEvidence:
    sources: list[ChatSource]
    citation_map: dict[int, ChatSource] = field(default_factory=dict)
    evidence_tokens: int = 0
    overhead_tokens: int = 0
    budget_tokens: int = 0
    truncated_sources: int = 0
    dropped_sources: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "source_count": len(self.sources),
            "evidence_tokens": self.evidence_tokens,
            "overhead_tokens": self.overhead_tokens,
            "budget_tokens": self.budget_tokens,
            "truncated_sources": self.truncated_sources,
            "dropped_sources": self.dropped_sources,
            "citation_ids": list(self.citation_map.keys()),
        }


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN + 0.999))


def pack_evidence_for_prompt(
    sources: list[ChatSource],
    *,
    question: str,
    history: list[dict[str, str]] | None = None,
    memory_block: str | None = None,
    instructions_text: str = "",
    context_tokens: int = 8192,
    output_reserve_tokens: int = 1024,
    margin_tokens: int = 256,
    per_source_cap_tokens: int = 1800,
) -> PackedEvidence:
    """Fit evidence into the remaining prompt budget after fixed overhead."""
    history_text = _history_text(history)
    overhead = (
        estimate_tokens(instructions_text)
        + estimate_tokens(question)
        + estimate_tokens(history_text)
        + estimate_tokens(memory_block or "")
        + max(0, output_reserve_tokens)
        + max(0, margin_tokens)
        + estimate_tokens("SOURCES:\n")
    )
    budget = max(0, int(context_tokens) - overhead)
    packed: list[ChatSource] = []
    used = 0
    truncated = 0
    dropped = 0
    cap_chars = max(200, int(per_source_cap_tokens * _CHARS_PER_TOKEN))

    for index, source in enumerate(sources):
        remaining = budget - used
        if remaining <= 32:
            dropped = len(sources) - index
            break
        original = source.content or source.snippet or ""
        excerpt = _preserve_structure_excerpt(
            original, question=question, max_chars=min(cap_chars, remaining * 4)
        )
        candidate = (
            source.model_copy(update={"content": excerpt})
            if excerpt != original
            else source
        )
        provisional_index = len(packed) + 1
        block = _source_block_for(candidate, provisional_index)
        cost = estimate_tokens(block)
        if cost > remaining:
            tighter = _preserve_structure_excerpt(
                original,
                question=question,
                max_chars=max(120, remaining * 3),
            )
            candidate = source.model_copy(update={"content": tighter})
            block = _source_block_for(candidate, provisional_index)
            cost = estimate_tokens(block)
            if cost > remaining:
                dropped += 1
                continue
            truncated += 1
        elif excerpt != original:
            truncated += 1
        packed.append(candidate)
        used += cost

    citation_map = {index: source for index, source in enumerate(packed, start=1)}
    return PackedEvidence(
        sources=packed,
        citation_map=citation_map,
        evidence_tokens=used,
        overhead_tokens=overhead,
        budget_tokens=budget,
        truncated_sources=truncated,
        dropped_sources=dropped,
    )


def render_packed_source_block(packed: PackedEvidence) -> str:
    return build_source_block(packed.sources)


def _source_block_for(source: ChatSource, index: int) -> str:
    location_bits = []
    if source.page_number is not None:
        location_bits.append(f"page {source.page_number}")
    if source.section_title:
        location_bits.append(source.section_title)
    location = f" ({', '.join(location_bits)})" if location_bits else ""
    excerpt = source.content or source.snippet or ""
    return (
        f"[SOURCE {index}] {source.file_name}{location}\n"
        f"Path: {source.file_path}\n"
        f"Chunk ID: {source.chunk_id}\n"
        f"Excerpt: {excerpt}"
    )


def _history_text(history: list[dict[str, str]] | None) -> str:
    if not history:
        return ""
    parts: list[str] = []
    for message in history[-12:]:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")[:600]
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


def _preserve_structure_excerpt(text: str, *, question: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text

    # Prefer windows that keep table rows / code fences when present.
    if _CODE_OR_ROW_RE.search(text):
        lines = text.splitlines()
        kept: list[str] = []
        size = 0
        # Keep header-ish first line, then matching structural lines.
        for line in lines:
            if not kept or _CODE_OR_ROW_RE.search(line) or any(
                term in line.lower()
                for term in _query_terms(question)[:8]
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
    seen: set[str] = set()
    terms: list[str] = []
    for term in re.findall(r"[\w\-]{3,}", (question or "").lower()):
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms
