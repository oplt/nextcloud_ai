from __future__ import annotations

import re
from dataclasses import dataclass

from ..parsers.document_parser import ParsedDocument, ParsedPage
from ..rag.chunker import (
    DEFAULT_CHILD_CHUNK_SIZE,
    DEFAULT_CHILD_OVERLAP,
    ChunkDraft,
    HeadingTableAwareChunker,
    RagChunkDraft,
    build_parent_chunks,
)
from ..rag.parser import RagParser

_WORD_RE = re.compile(r"\S+")

# Canonical evidence draft — shared with rag.chunker.
__all__ = [
    "ChunkDraft",
    "RagChunkDraft",
    "Span",
    "build_parent_chunks",
    "chunk_parsed_document",
]


@dataclass(slots=True)
class Span:
    start: int
    end: int


def chunk_parsed_document(
    parsed: ParsedDocument,
    *,
    chunk_size: int = 400,
    overlap: int = 60,
    include_parents: bool = False,
    parent_size: int | None = None,
) -> list[ChunkDraft]:
    """Chunk a parsed document into canonical ChunkDraft evidence units.

    Default child size 250–500 tokens with 40–80 overlap is a starting grid;
    callers may override. The default chunker uses a versioned conservative
    Unicode token budget; the fallback path retains its legacy word spans.
    """
    size = max(40, chunk_size or DEFAULT_CHILD_CHUNK_SIZE)
    ov = max(
        0, min(overlap if overlap is not None else DEFAULT_CHILD_OVERLAP, size - 1)
    )
    rag_document = RagParser().normalize(parsed)
    rag_drafts = HeadingTableAwareChunker(chunk_size=size, overlap=ov).chunk(
        rag_document
    )
    if rag_drafts:
        children = list(rag_drafts)
        if include_parents:
            return build_parent_chunks(
                children, parent_size=parent_size, child_size=size
            )
        return children

    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    drafts: list[ChunkDraft] = []
    global_offset = 0
    pages = parsed.pages or [ParsedPage(page_number=None, text=parsed.text)]

    for page in pages:
        for draft in _chunk_text(
            page.text,
            chunk_size=chunk_size,
            overlap=overlap,
            global_offset=global_offset,
            page_number=page.page_number,
            chunk_index_start=len(drafts),
        ):
            drafts.append(draft)
        global_offset += len(page.text) + 2

    if not drafts and parsed.text.strip():
        drafts.extend(
            _chunk_text(
                parsed.text,
                chunk_size=chunk_size,
                overlap=overlap,
                global_offset=0,
                page_number=None,
                chunk_index_start=0,
            )
        )

    for idx, draft in enumerate(drafts):
        draft.chunk_index = idx
    return drafts


def _chunk_text(
    text: str,
    *,
    chunk_size: int,
    overlap: int,
    global_offset: int,
    page_number: int | None,
    chunk_index_start: int,
) -> list[ChunkDraft]:
    spans = [Span(match.start(), match.end()) for match in _WORD_RE.finditer(text)]
    if not spans:
        return []

    step = max(1, chunk_size - overlap)
    drafts: list[ChunkDraft] = []
    for index, word_start in enumerate(
        range(0, len(spans), step), start=chunk_index_start
    ):
        word_end = min(word_start + chunk_size, len(spans))
        char_start = spans[word_start].start
        char_end = spans[word_end - 1].end
        content = text[char_start:char_end].strip()
        drafts.append(
            ChunkDraft(
                chunk_index=index,
                content=content,
                token_count=word_end - word_start,
                char_start=global_offset + char_start,
                char_end=global_offset + char_end,
                page_number=page_number,
                metadata={
                    "source_char_start": global_offset + char_start,
                    "source_char_end": global_offset + char_end,
                    "chunker": "fallback-word-v2",
                },
            )
        )
        if word_end >= len(spans):
            break
    return drafts
