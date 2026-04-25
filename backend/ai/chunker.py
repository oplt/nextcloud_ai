from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from ..parsers.document_parser import ParsedDocument, ParsedPage
from ..rag.chunker import HeadingTableAwareChunker
from ..rag.parser import RagParser

_WORD_RE = re.compile(r"\S+")


@dataclass(slots=True)
class ChunkDraft:
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


@dataclass(slots=True)
class Span:
    start: int
    end: int


def chunk_parsed_document(
        parsed: ParsedDocument, *, chunk_size: int = 220, overlap: int = 40
) -> list[ChunkDraft]:
    rag_document = RagParser().normalize(parsed)
    rag_drafts = HeadingTableAwareChunker(
        chunk_size=max(chunk_size, 280),
        overlap=overlap,
    ).chunk(rag_document)
    if rag_drafts:
        return [
            ChunkDraft(
                chunk_index=draft.chunk_index,
                content=draft.content,
                token_count=draft.token_count,
                char_start=draft.char_start,
                char_end=draft.char_end,
                page_number=draft.page_number,
                section_title=draft.section_title,
                heading_path=draft.heading_path,
                metadata=draft.metadata,
            )
            for draft in rag_drafts
        ]

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

    step = chunk_size - overlap
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
            )
        )
    return drafts
