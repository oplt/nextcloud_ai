from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..parsers.document_parser import ParsedDocument

_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_PLAIN_HEADING_RE = re.compile(r"^[A-Z][A-Za-z0-9][A-Za-z0-9 &'’/(),.-]{1,90}$")


@dataclass(slots=True)
class RagBlock:
    text: str
    block_type: str = "paragraph"
    page_number: int | None = None
    section_title: str | None = None
    heading_path: str | None = None
    char_start: int = 0
    char_end: int = 0
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class RagParsedDocument:
    text: str
    blocks: list[RagBlock]
    metadata: dict[str, object]


class RagParser:
    """Normalize parser output into structure-aware RAG blocks.

    The source parsers still own file-type extraction. This layer adds the
    document understanding needed by chunking: headings, table-like regions,
    page numbers, and character provenance.
    """

    def normalize(self, parsed: ParsedDocument) -> RagParsedDocument:
        blocks: list[RagBlock] = []
        pages = parsed.pages or []
        running_offset = 0

        if pages:
            for page in pages:
                page_blocks = self._blocks_from_text(
                    page.text,
                    page_number=page.page_number,
                    global_offset=running_offset,
                )
                blocks.extend(page_blocks)
                running_offset += len(page.text) + 2
        else:
            blocks.extend(
                self._blocks_from_text(
                    parsed.text,
                    page_number=None,
                    global_offset=0,
                )
            )

        if not blocks and parsed.text.strip():
            stripped = parsed.text.strip()
            blocks.append(
                RagBlock(
                    text=stripped,
                    page_number=None,
                    char_start=0,
                    char_end=len(stripped),
                    metadata={"parser_fallback": True},
                )
            )

        return RagParsedDocument(
            text=parsed.text,
            blocks=blocks,
            metadata=dict(parsed.metadata or {}),
        )

    def _blocks_from_text(
        self, text: str, *, page_number: int | None, global_offset: int
    ) -> list[RagBlock]:
        blocks: list[RagBlock] = []
        heading_stack: list[str] = []
        paragraph_lines: list[tuple[str, int, int]] = []
        table_lines: list[tuple[str, int, int]] = []

        def current_heading_path() -> str | None:
            return " > ".join(heading_stack) if heading_stack else None

        def flush_paragraph() -> None:
            if not paragraph_lines:
                return
            raw = "\n".join(line for line, _, _ in paragraph_lines).strip()
            if raw:
                blocks.append(
                    RagBlock(
                        text=raw,
                        block_type="paragraph",
                        page_number=page_number,
                        section_title=heading_stack[-1] if heading_stack else None,
                        heading_path=current_heading_path(),
                        char_start=global_offset + paragraph_lines[0][1],
                        char_end=global_offset + paragraph_lines[-1][2],
                    )
                )
            paragraph_lines.clear()

        def flush_table() -> None:
            if not table_lines:
                return
            raw = "\n".join(line for line, _, _ in table_lines).strip()
            if raw:
                blocks.append(
                    RagBlock(
                        text=raw,
                        block_type="table",
                        page_number=page_number,
                        section_title=heading_stack[-1] if heading_stack else None,
                        heading_path=current_heading_path(),
                        char_start=global_offset + table_lines[0][1],
                        char_end=global_offset + table_lines[-1][2],
                        metadata={"table_line_count": len(table_lines)},
                    )
                )
            table_lines.clear()

        cursor = 0
        for raw_line in text.splitlines():
            line_start = cursor
            line_end = cursor + len(raw_line)
            cursor = line_end + 1
            line = raw_line.strip()

            if not line:
                flush_paragraph()
                flush_table()
                continue

            heading_level, heading_text = _detect_heading(line)
            if heading_text:
                flush_paragraph()
                flush_table()
                heading_stack = heading_stack[: heading_level - 1]
                heading_stack.append(heading_text)
                blocks.append(
                    RagBlock(
                        text=heading_text,
                        block_type="heading",
                        page_number=page_number,
                        section_title=heading_text,
                        heading_path=current_heading_path(),
                        char_start=global_offset + line_start,
                        char_end=global_offset + line_end,
                        metadata={"heading_level": heading_level},
                    )
                )
                continue

            if _looks_like_table_line(line):
                flush_paragraph()
                table_lines.append((line, line_start, line_end))
                continue

            flush_table()
            paragraph_lines.append((line, line_start, line_end))

        flush_paragraph()
        flush_table()
        return blocks


def _detect_heading(line: str) -> tuple[int, str | None]:
    match = _MARKDOWN_HEADING_RE.match(line)
    if match:
        return len(match.group(1)), match.group(2).strip()
    if (
        len(line) <= 90
        and not line.endswith((".", ",", ";", ":"))
        and _PLAIN_HEADING_RE.match(line)
        and len(line.split()) <= 10
    ):
        return 2, line
    return 1, None


def _looks_like_table_line(line: str) -> bool:
    if "|" in line and line.count("|") >= 2:
        return True
    if "\t" in line and len([part for part in line.split("\t") if part.strip()]) >= 2:
        return True
    return bool(re.search(r"\S+\s{2,}\S+\s{2,}\S+", line))

