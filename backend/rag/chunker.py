from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .parser import RagBlock, RagParsedDocument

_WORD_RE = re.compile(r"\S+")


@dataclass(slots=True)
class RagChunkDraft:
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


class HeadingTableAwareChunker:
    def __init__(
        self,
        *,
        chunk_size: int = 280,
        overlap: int = 45,
        min_group_tokens: int = 32,
        table_context_tokens: int = 80,
    ) -> None:
        if overlap >= chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.min_group_tokens = min_group_tokens
        self.table_context_tokens = table_context_tokens

    def chunk(self, parsed: RagParsedDocument) -> list[RagChunkDraft]:
        drafts: list[RagChunkDraft] = []
        buffer: list[RagBlock] = []
        buffer_tokens = 0
        buffer_heading_path: str | None = None

        def flush() -> None:
            nonlocal buffer, buffer_tokens, buffer_heading_path
            if not buffer:
                return
            drafts.append(self._draft_from_blocks(buffer, len(drafts)))
            if self.overlap <= 0:
                buffer = []
                buffer_tokens = 0
                buffer_heading_path = None
                return
            kept: list[RagBlock] = []
            kept_tokens = 0
            for block in reversed(buffer):
                block_tokens = _count_words(block.text)
                if kept and kept_tokens + block_tokens > self.overlap:
                    break
                kept.insert(0, block)
                kept_tokens += block_tokens
            buffer = kept
            buffer_tokens = kept_tokens
            buffer_heading_path = kept[-1].heading_path if kept else None

        text_blocks = [block for block in parsed.blocks if block.block_type != "heading"]
        for block_index, block in enumerate(text_blocks):
            block_tokens = _count_words(block.text)

            if block.block_type == "table":
                flush()
                table_block = self._block_with_context(text_blocks, block_index)
                drafts.extend(self._split_block(table_block, len(drafts), table=True))
                continue

            if block_tokens > self.chunk_size:
                flush()
                drafts.extend(self._split_block(block, len(drafts), table=False))
                continue

            heading_changed = (
                buffer
                and buffer_heading_path != block.heading_path
                and buffer_tokens >= self.min_group_tokens
            )
            too_large = buffer and buffer_tokens + block_tokens > self.chunk_size
            if heading_changed or too_large:
                flush()
            buffer.append(block)
            buffer_tokens += block_tokens
            buffer_heading_path = block.heading_path

        flush()
        for index, draft in enumerate(drafts):
            draft.chunk_index = index
            draft.metadata["chunker"] = "title-token-v1"
        return drafts

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

        text = "\n".join(
            part
            for part in [
                f"Context above:\n{context_above}" if context_above else "",
                block.text,
                f"Context below:\n{context_below}" if context_below else "",
            ]
            if part
        )
        return RagBlock(
            text=text,
            block_type=block.block_type,
            page_number=block.page_number,
            section_title=block.section_title,
            heading_path=block.heading_path,
            char_start=block.char_start,
            char_end=block.char_end,
            metadata={
                **block.metadata,
                "context_above_tokens": _count_words(context_above),
                "context_below_tokens": _count_words(context_below),
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
            if block.block_type != "paragraph":
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
        step = self.chunk_size if table else self.chunk_size - self.overlap
        drafts: list[RagChunkDraft] = []
        for offset, word_start in enumerate(range(0, len(words), step)):
            word_end = min(word_start + self.chunk_size, len(words))
            char_start = words[word_start].start()
            char_end = words[word_end - 1].end()
            text = block.text[char_start:char_end].strip()
            drafts.append(
                RagChunkDraft(
                    chunk_index=chunk_index_start + offset,
                    content=_prefix_with_section(text, block),
                    token_count=word_end - word_start,
                    char_start=block.char_start + char_start,
                    char_end=block.char_start + char_end,
                    page_number=block.page_number,
                    section_title=block.section_title,
                    heading_path=block.heading_path,
                    metadata={
                        **block.metadata,
                        "block_type": "table" if table else block.block_type,
                        "split_from_large_block": True,
                    },
                )
            )
        return drafts

    @staticmethod
    def _draft_from_blocks(blocks: list[RagBlock], chunk_index: int) -> RagChunkDraft:
        content = "\n\n".join(block.text for block in blocks).strip()
        first = blocks[0]
        last = blocks[-1]
        section_title = last.section_title or first.section_title
        heading_path = last.heading_path or first.heading_path
        return RagChunkDraft(
            chunk_index=chunk_index,
            content=_prefix_with_section(content, last),
            token_count=_count_words(content),
            char_start=first.char_start,
            char_end=last.char_end,
            page_number=first.page_number if first.page_number == last.page_number else None,
            section_title=section_title,
            heading_path=heading_path,
            metadata={
                "block_types": list(dict.fromkeys(block.block_type for block in blocks)),
                "block_count": len(blocks),
                "title_grouped": bool(heading_path),
            },
        )


def _count_words(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _prefix_with_section(text: str, block: RagBlock) -> str:
    if block.heading_path and not text.startswith(block.heading_path):
        return f"{block.heading_path}\n{text}"
    return text
