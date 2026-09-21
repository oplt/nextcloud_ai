from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .parser import RagBlock, RagParsedDocument

_WORD_RE = re.compile(r"\S+")

# Starting child/parent hypotheses (word-token approximations).
CHILD_CHUNK_SIZE_GRID = (250, 400, 500)
CHILD_OVERLAP_GRID = (40, 60, 80)
DEFAULT_CHILD_CHUNK_SIZE = 400
DEFAULT_CHILD_OVERLAP = 60
DEFAULT_PARENT_MULTIPLIER = 3


@dataclass(slots=True)
class RagChunkDraft:
    """Canonical chunk/evidence draft used by RAG and AI chunking paths."""

    chunk_index: int
    content: str
    token_count: int
    char_start: int
    char_end: int
    page_number: int | None = None
    section_title: str | None = None
    heading_path: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


# Compatibility alias — one canonical evidence type.
ChunkDraft = RagChunkDraft


class HeadingTableAwareChunker:
    def __init__(
        self,
        *,
        chunk_size: int = DEFAULT_CHILD_CHUNK_SIZE,
        overlap: int = DEFAULT_CHILD_OVERLAP,
        min_group_tokens: int = 32,
        table_context_tokens: int = 30,
    ) -> None:
        if overlap >= chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")
        if overlap < 0:
            raise ValueError("overlap must be >= 0")
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.min_group_tokens = min_group_tokens
        self.table_context_tokens = table_context_tokens

    def chunk(self, parsed: RagParsedDocument) -> list[RagChunkDraft]:
        drafts: list[RagChunkDraft] = []
        buffer: list[RagBlock] = []
        buffer_tokens = 0
        buffer_heading_path: str | None = None

        def flush(*, keep_overlap: bool = True) -> None:
            nonlocal buffer, buffer_tokens, buffer_heading_path
            if not buffer:
                return
            draft = self._draft_from_blocks(buffer, len(drafts))
            if draft is not None:
                drafts.append(draft)
            if not keep_overlap or self.overlap <= 0:
                buffer = []
                buffer_tokens = 0
                buffer_heading_path = None
                return
            # Only retain overlap when we actually emitted a real chunk.
            if draft is None:
                buffer = []
                buffer_tokens = 0
                buffer_heading_path = None
                return
            buffer, buffer_tokens = self._overlap_residue(buffer)
            buffer_heading_path = buffer[-1].heading_path if buffer else None

        text_blocks = [
            block for block in parsed.blocks if block.block_type != "heading"
        ]
        for block_index, block in enumerate(text_blocks):
            block_tokens = _count_words(block.text)

            if block.block_type == "table":
                # Drop paragraph overlap before/after tables — prevents
                # paragraph → table → end emitting an overlap-only final chunk.
                flush(keep_overlap=False)
                table_block = self._block_with_context(text_blocks, block_index)
                drafts.extend(self._split_block(table_block, len(drafts), table=True))
                buffer = []
                buffer_tokens = 0
                buffer_heading_path = None
                continue

            if block.block_type == "code" and block_tokens > self.chunk_size:
                flush(keep_overlap=False)
                drafts.extend(self._split_code_block(block, len(drafts)))
                continue

            if block_tokens > self.chunk_size:
                flush(keep_overlap=False)
                drafts.extend(self._split_block(block, len(drafts), table=False))
                continue

            heading_changed = (
                buffer
                and buffer_heading_path != block.heading_path
                and buffer_tokens >= self.min_group_tokens
            )
            page_changed = (
                buffer
                and buffer[0].page_number is not None
                and block.page_number is not None
                and buffer[0].page_number != block.page_number
                and buffer_tokens >= self.min_group_tokens
            )
            too_large = buffer and buffer_tokens + block_tokens > self.chunk_size
            if heading_changed or page_changed or too_large:
                flush(keep_overlap=not (heading_changed or page_changed))
                while buffer and buffer_tokens + block_tokens > self.chunk_size:
                    draft = self._draft_from_blocks(buffer, len(drafts))
                    if draft is not None:
                        drafts.append(draft)
                    buffer, buffer_tokens = self._overlap_residue(buffer)
                    if not buffer:
                        break
                    if buffer_tokens > self.chunk_size:
                        drafts.extend(
                            self._split_block(buffer[0], len(drafts), table=False)
                        )
                        buffer, buffer_tokens = [], 0
                        break
            buffer.append(block)
            buffer_tokens += block_tokens
            buffer_heading_path = block.heading_path

        flush(keep_overlap=False)
        return self._finalize_drafts(drafts)

    def _finalize_drafts(self, drafts: list[RagChunkDraft]) -> list[RagChunkDraft]:
        """Drop overlap-only/duplicate tails; enforce token budget; reindex."""
        cleaned: list[RagChunkDraft] = []
        seen_hashes: set[str] = set()
        prev_source: tuple[int, int] | None = None
        for draft in drafts:
            if draft.metadata.get("overlap_only"):
                continue
            source_start = int(draft.metadata.get("source_char_start", draft.char_start))
            source_end = int(draft.metadata.get("source_char_end", draft.char_end))
            if source_end < source_start:
                continue
            # Drop exact duplicate tails (same source span emitted twice).
            if prev_source == (source_start, source_end):
                continue
            body_hash = hashlib.sha256(
                f"{source_start}:{source_end}:{draft.content}".encode()
            ).hexdigest()
            if body_hash in seen_hashes:
                continue
            seen_hashes.add(body_hash)
            # Enforce budget including any prefixes already in content.
            if draft.token_count > self.chunk_size:
                draft = self._trim_draft_to_budget(draft)
            cleaned.append(draft)
            prev_source = (source_start, source_end)

        # Monotonic source order (stable by original emission, then start).
        cleaned.sort(key=lambda d: (int(d.metadata.get("source_char_start", d.char_start)), d.chunk_index))
        for index, draft in enumerate(cleaned):
            draft.chunk_index = index
            draft.metadata["chunker"] = "title-token-v2"
            draft.token_count = _count_words(draft.content)
        return cleaned

    def _trim_draft_to_budget(self, draft: RagChunkDraft) -> RagChunkDraft:
        """Prefer dropping synthetic prefixes; then trim body words to chunk_size."""
        meta = dict(draft.metadata or {})
        body = str(meta.get("source_body") or draft.content)
        # Rebuild without exceeding budget: body first, then heading if room.
        content, extra = _compose_chunk_content(
            body,
            heading_path=draft.heading_path,
            context_above=str(meta.get("context_above") or ""),
            context_below=str(meta.get("context_below") or ""),
            max_tokens=self.chunk_size,
        )
        draft.content = content
        draft.token_count = _count_words(content)
        draft.metadata = {**meta, **extra, "trimmed_to_budget": True}
        return draft

    def _overlap_residue(
        self, buffer: list[RagBlock]
    ) -> tuple[list[RagBlock], int]:
        """Keep at most ``overlap`` trailing words — never a whole oversized block."""
        if not buffer or self.overlap <= 0:
            return [], 0
        real = [b for b in buffer if b.block_type != "overlap"]
        if not real:
            return [], 0
        combined = "\n\n".join(block.text for block in real)
        words = list(_WORD_RE.finditer(combined))
        if not words:
            return [], 0
        take_n = min(self.overlap, len(words))
        take = words[-take_n:]
        start = take[0].start()
        end = take[-1].end()
        overlap_text = combined[start:end]
        last = real[-1]
        # Map trailing overlap onto the last real block's source span.
        if last.text and overlap_text.endswith(
            last.text[-min(len(last.text), len(overlap_text)) :]
        ):
            suffix_len = min(len(last.text), len(overlap_text))
            local_start = max(0, len(last.text) - suffix_len)
            char_start = last.char_start + local_start
        else:
            char_start = last.char_start
        residue = RagBlock(
            text=overlap_text,
            block_type="overlap",
            page_number=last.page_number,
            section_title=last.section_title,
            heading_path=last.heading_path,
            char_start=char_start,
            char_end=last.char_end,
            metadata={
                "synthetic_overlap": True,
                "source_block_type": last.block_type,
            },
        )
        return [residue], _count_words(overlap_text)

    def _block_with_context(self, blocks: list[RagBlock], block_index: int) -> RagBlock:
        block = blocks[block_index]
        if self.table_context_tokens <= 0:
            return block

        context_above = self._nearby_text_context(
            blocks[:block_index], self.table_context_tokens, from_end=True
        )
        context_below = self._nearby_text_context(
            blocks[block_index + 1 :], self.table_context_tokens, from_end=False
        )
        if not context_above and not context_below:
            return block

        return RagBlock(
            text=block.text,
            block_type=block.block_type,
            page_number=block.page_number,
            section_title=block.section_title,
            heading_path=block.heading_path,
            char_start=block.char_start,
            char_end=block.char_end,
            metadata={
                **block.metadata,
                "context_above": context_above,
                "context_below": context_below,
                "context_above_tokens": _count_words(context_above),
                "context_below_tokens": _count_words(context_below),
                "source_char_start": block.char_start,
                "source_char_end": block.char_end,
            },
        )

    @staticmethod
    def _nearby_text_context(
        blocks: list[RagBlock], token_budget: int, *, from_end: bool
    ) -> str:
        selected: list[str] = []
        remaining = token_budget
        iterable = reversed(blocks) if from_end else iter(blocks)
        for block in iterable:
            if block.block_type not in {"paragraph", "list"}:
                continue
            text = block.text.strip()
            if not text:
                continue
            tokens = _WORD_RE.findall(text)
            if not tokens:
                continue
            if len(tokens) > remaining:
                snippet_tokens = tokens[-remaining:] if from_end else tokens[:remaining]
                selected_text = " ".join(snippet_tokens)
                if from_end:
                    selected.insert(0, selected_text)
                else:
                    selected.append(selected_text)
                break
            if from_end:
                selected.insert(0, text)
            else:
                selected.append(text)
            remaining -= len(tokens)
            if remaining <= 0:
                break
        return "\n".join(selected).strip()

    def _split_block(
        self, block: RagBlock, chunk_index_start: int, *, table: bool
    ) -> list[RagChunkDraft]:
        words = list(_WORD_RE.finditer(block.text))
        if not words:
            return []
        header_prefix = ""
        header_tokens = 0
        if table:
            first_line = block.text.splitlines()[0] if block.text else ""
            if first_line.strip().startswith("|"):
                header_prefix = first_line.strip()
                header_tokens = _count_words(header_prefix)

        body_budget = max(1, self.chunk_size - (header_tokens if table else 0))
        step = body_budget if table else max(1, self.chunk_size - self.overlap)
        drafts: list[RagChunkDraft] = []

        for offset, word_start in enumerate(range(0, len(words), step)):
            word_end = min(word_start + body_budget, len(words))
            char_start = words[word_start].start()
            char_end = words[word_end - 1].end()
            text = block.text[char_start:char_end].strip()
            if (
                table
                and header_prefix
                and offset > 0
                and not text.startswith(header_prefix)
            ):
                text = f"{header_prefix}\n{text}"
            content, meta_extra = _compose_chunk_content(
                text,
                heading_path=block.heading_path,
                context_above=str((block.metadata or {}).get("context_above") or ""),
                context_below=str((block.metadata or {}).get("context_below") or ""),
                max_tokens=self.chunk_size,
            )
            drafts.append(
                RagChunkDraft(
                    chunk_index=chunk_index_start + offset,
                    content=content,
                    token_count=_count_words(content),
                    char_start=block.char_start + char_start,
                    char_end=block.char_start + char_end,
                    page_number=block.page_number,
                    section_title=block.section_title,
                    heading_path=block.heading_path,
                    metadata={
                        **dict(block.metadata or {}),
                        **meta_extra,
                        "block_type": "table" if table else block.block_type,
                        "split_from_large_block": True,
                        "source_body": block.text[char_start:char_end].strip(),
                        "source_char_start": block.char_start + char_start,
                        "source_char_end": block.char_start + char_end,
                        "repeated_table_header": bool(
                            table and header_prefix and offset > 0
                        ),
                    },
                )
            )
            if word_end >= len(words):
                break
        return drafts

    def _split_code_block(
        self, block: RagBlock, chunk_index_start: int
    ) -> list[RagChunkDraft]:
        language = str((block.metadata or {}).get("language") or "").lower()
        lines = block.text.splitlines(keepends=True)
        if not lines:
            return self._split_block(block, chunk_index_start, table=False)

        boundary_re = None
        if language in {"python", "py"}:
            boundary_re = re.compile(r"^(def |class |async def )")
        elif language in {"javascript", "typescript", "js", "ts"}:
            boundary_re = re.compile(
                r"^(export )?(async )?(function |class |const \w+ = (async )?\()"
            )

        segments: list[str] = []
        current: list[str] = []
        for line in lines:
            if (
                boundary_re
                and current
                and boundary_re.match(line)
                and _count_words("".join(current)) >= self.min_group_tokens
            ):
                segments.append("".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            segments.append("".join(current))

        drafts: list[RagChunkDraft] = []
        cursor = 0
        for segment in segments:
            local_start = block.text.find(segment, cursor)
            if local_start < 0:
                local_start = cursor
            local_end = local_start + len(segment)
            cursor = local_end
            seg_block = RagBlock(
                text=segment.rstrip("\n"),
                block_type="code",
                page_number=block.page_number,
                section_title=block.section_title,
                heading_path=block.heading_path,
                char_start=block.char_start + local_start,
                char_end=block.char_start + local_end,
                metadata=dict(block.metadata or {}),
            )
            if _count_words(seg_block.text) > self.chunk_size:
                drafts.extend(
                    self._split_block(
                        seg_block, chunk_index_start + len(drafts), table=False
                    )
                )
            else:
                content, meta_extra = _compose_chunk_content(
                    seg_block.text,
                    heading_path=seg_block.heading_path,
                    max_tokens=self.chunk_size,
                )
                drafts.append(
                    RagChunkDraft(
                        chunk_index=chunk_index_start + len(drafts),
                        content=content,
                        token_count=_count_words(content),
                        char_start=seg_block.char_start,
                        char_end=seg_block.char_end,
                        page_number=seg_block.page_number,
                        section_title=seg_block.section_title,
                        heading_path=seg_block.heading_path,
                        metadata={
                            **seg_block.metadata,
                            **meta_extra,
                            "block_type": "code",
                            "source_body": seg_block.text,
                            "source_char_start": seg_block.char_start,
                            "source_char_end": seg_block.char_end,
                        },
                    )
                )
        return drafts

    def _draft_from_blocks(
        self, blocks: list[RagBlock], chunk_index: int
    ) -> RagChunkDraft | None:
        real_blocks = [b for b in blocks if b.block_type != "overlap"]
        if not real_blocks:
            # Never emit overlap-only chunks (duplicate tails).
            return None
        body = "\n\n".join(block.text for block in real_blocks).strip()
        if not body:
            return None
        first = real_blocks[0]
        last = real_blocks[-1]
        # When overlap residue leads the buffer, source start is first *real* block.
        section_title = last.section_title or first.section_title
        heading_path = last.heading_path or first.heading_path
        content, meta_extra = _compose_chunk_content(
            body,
            heading_path=heading_path,
            context_above=str((last.metadata or {}).get("context_above") or ""),
            context_below=str((last.metadata or {}).get("context_below") or ""),
            max_tokens=self.chunk_size,
        )
        return RagChunkDraft(
            chunk_index=chunk_index,
            content=content,
            token_count=_count_words(content),
            char_start=first.char_start,
            char_end=last.char_end,
            page_number=first.page_number
            if first.page_number == last.page_number
            else None,
            section_title=section_title,
            heading_path=heading_path,
            metadata={
                "block_types": list(
                    dict.fromkeys(block.block_type for block in real_blocks)
                ),
                "block_count": len(real_blocks),
                "title_grouped": bool(heading_path),
                "source_body": body,
                "source_char_start": first.char_start,
                "source_char_end": last.char_end,
                **meta_extra,
            },
        )


def build_parent_chunks(
    children: list[RagChunkDraft],
    *,
    parent_size: int | None = None,
    child_size: int = DEFAULT_CHILD_CHUNK_SIZE,
) -> list[RagChunkDraft]:
    """Group consecutive children into larger parent evidence windows."""
    if not children:
        return []
    window = parent_size or (child_size * DEFAULT_PARENT_MULTIPLIER)
    parents: list[RagChunkDraft] = []
    bucket: list[RagChunkDraft] = []
    bucket_tokens = 0
    for child in children:
        child_tokens = child.token_count or _count_words(child.content)
        if bucket and bucket_tokens + child_tokens > window:
            parents.append(_parent_from_children(bucket, len(parents)))
            bucket, bucket_tokens = [], 0
        bucket.append(child)
        bucket_tokens += child_tokens
    if bucket:
        parents.append(_parent_from_children(bucket, len(parents)))
    return parents


def _parent_from_children(
    children: list[RagChunkDraft], index: int
) -> RagChunkDraft:
    first, last = children[0], children[-1]
    content = "\n\n".join(c.content for c in children)
    return RagChunkDraft(
        chunk_index=index,
        content=content,
        token_count=_count_words(content),
        char_start=first.char_start,
        char_end=last.char_end,
        page_number=first.page_number
        if first.page_number == last.page_number
        else None,
        section_title=last.section_title or first.section_title,
        heading_path=last.heading_path or first.heading_path,
        metadata={
            "chunker": "title-token-v2-parent",
            "child_count": len(children),
            "child_indexes": [c.chunk_index for c in children],
            "source_char_start": first.char_start,
            "source_char_end": last.char_end,
        },
    )


def _count_words(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _compose_chunk_content(
    body: str,
    *,
    heading_path: str | None = None,
    context_above: str = "",
    context_below: str = "",
    max_tokens: int | None = None,
) -> tuple[str, dict[str, object]]:
    """Build content with synthetic prefixes under an optional token budget.

    Source spans always refer to ``body`` only. Prefixes that would exceed the
    budget stay in metadata and are omitted from ``content``.
    """
    meta: dict[str, object] = {"source_body": body}
    body_tokens = _count_words(body)
    parts: list[str] = []
    used = 0

    if heading_path and not body.startswith(heading_path):
        heading_tokens = _count_words(heading_path)
        meta["context_heading"] = heading_path
        if max_tokens is None or heading_tokens + body_tokens <= max_tokens:
            parts.append(heading_path)
            used += heading_tokens
        else:
            meta["context_heading_omitted_for_budget"] = True

    if context_above:
        above = f"Context above:\n{context_above}"
        above_tokens = _count_words(above)
        meta["context_above"] = context_above
        if max_tokens is None or used + above_tokens + body_tokens <= max_tokens:
            parts.append(above)
            used += above_tokens
        else:
            meta["context_above_omitted_for_budget"] = True

    if max_tokens is not None and body_tokens > max_tokens:
        words = list(_WORD_RE.finditer(body))
        cut = words[max_tokens - 1].end() if words else len(body)
        body = body[:cut].strip()
        meta["source_body_trimmed"] = True
        meta["source_body"] = body
    parts.append(body)

    if context_below:
        below = f"Context below:\n{context_below}"
        below_tokens = _count_words(below)
        meta["context_below"] = context_below
        current = _count_words("\n".join(parts))
        if max_tokens is None or current + below_tokens <= max_tokens:
            parts.append(below)
        else:
            meta["context_below_omitted_for_budget"] = True

    return "\n".join(parts), meta
