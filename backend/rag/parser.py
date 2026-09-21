from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..parsers.document_parser import ParsedDocument

_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_PLAIN_HEADING_RE = re.compile(r"^[A-Z0-9][A-Za-z0-9][A-Za-z0-9 &'’/(),.-]{0,88}$")
_LIST_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+\S+")
_CODE_FENCE_RE = re.compile(r"^```(\w+)?\s*$")
_SENTENCE_HINT_RE = re.compile(
    r"\b(is|are|was|were|the|and|with|from|that|this|have|has|for|into)\b",
    re.IGNORECASE,
)


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
        heading_stack: list[str] = []

        if pages:
            for page_index, page in enumerate(pages):
                page_blocks, heading_stack = self._blocks_from_text(
                    page.text,
                    page_number=page.page_number,
                    global_offset=running_offset,
                    heading_stack=heading_stack,
                )
                blocks.extend(page_blocks)
                # Match ingestion join: pages combined with "\n\n"
                gap = 2 if page_index < len(pages) - 1 else 0
                running_offset += len(page.text) + gap
        else:
            page_blocks, heading_stack = self._blocks_from_text(
                parsed.text,
                page_number=None,
                global_offset=0,
                heading_stack=heading_stack,
            )
            blocks.extend(page_blocks)

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
        self,
        text: str,
        *,
        page_number: int | None,
        global_offset: int,
        heading_stack: list[str] | None = None,
    ) -> tuple[list[RagBlock], list[str]]:
        blocks: list[RagBlock] = []
        stack = list(heading_stack or [])
        paragraph_lines: list[tuple[str, int, int]] = []
        table_lines: list[tuple[str, int, int]] = []
        list_lines: list[tuple[str, int, int]] = []
        code_lines: list[tuple[str, int, int]] = []
        in_code = False
        code_language: str | None = None

        def current_heading_path() -> str | None:
            return " > ".join(stack) if stack else None

        def flush_paragraph() -> None:
            if not paragraph_lines:
                return
            # Preserve original line text (not stripped) for offset fidelity.
            raw = "\n".join(line for line, _, _ in paragraph_lines)
            raw_stripped = raw.strip()
            if raw_stripped:
                blocks.append(
                    RagBlock(
                        text=raw_stripped,
                        block_type="paragraph",
                        page_number=page_number,
                        section_title=stack[-1] if stack else None,
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
                        section_title=stack[-1] if stack else None,
                        heading_path=current_heading_path(),
                        char_start=global_offset + table_lines[0][1],
                        char_end=global_offset + table_lines[-1][2],
                        metadata={"table_line_count": len(table_lines)},
                    )
                )
            table_lines.clear()

        def flush_list() -> None:
            if not list_lines:
                return
            raw = "\n".join(line for line, _, _ in list_lines).strip()
            if raw:
                blocks.append(
                    RagBlock(
                        text=raw,
                        block_type="list",
                        page_number=page_number,
                        section_title=stack[-1] if stack else None,
                        heading_path=current_heading_path(),
                        char_start=global_offset + list_lines[0][1],
                        char_end=global_offset + list_lines[-1][2],
                        metadata={"list_item_count": len(list_lines)},
                    )
                )
            list_lines.clear()

        def flush_code() -> None:
            nonlocal in_code, code_language
            if not code_lines:
                in_code = False
                code_language = None
                return
            # Keep indentation from original lines.
            raw = "\n".join(line for line, _, _ in code_lines)
            if raw.strip():
                blocks.append(
                    RagBlock(
                        text=raw,
                        block_type="code",
                        page_number=page_number,
                        section_title=stack[-1] if stack else None,
                        heading_path=current_heading_path(),
                        char_start=global_offset + code_lines[0][1],
                        char_end=global_offset + code_lines[-1][2],
                        metadata={
                            "language": code_language,
                            "line_count": len(code_lines),
                        },
                    )
                )
            code_lines.clear()
            in_code = False
            code_language = None

        cursor = 0
        for raw_line in text.splitlines(keepends=False):
            line_start = cursor
            line_end = cursor + len(raw_line)
            cursor = line_end + 1
            stripped = raw_line.strip()

            fence = _CODE_FENCE_RE.match(stripped)
            if fence:
                flush_paragraph()
                flush_table()
                flush_list()
                if in_code:
                    flush_code()
                else:
                    in_code = True
                    code_language = fence.group(1)
                continue

            if in_code:
                code_lines.append((raw_line, line_start, line_end))
                continue

            if not stripped:
                flush_paragraph()
                flush_table()
                flush_list()
                continue

            heading_level, heading_text = _detect_heading(stripped)
            if heading_text:
                flush_paragraph()
                flush_table()
                flush_list()
                stack = stack[: heading_level - 1]
                stack.append(heading_text)
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

            if _LIST_RE.match(stripped):
                flush_paragraph()
                flush_table()
                list_lines.append((stripped, line_start, line_end))
                continue

            if _looks_like_table_line(stripped):
                flush_paragraph()
                flush_list()
                table_lines.append((stripped, line_start, line_end))
                continue

            flush_table()
            flush_list()
            paragraph_lines.append((stripped, line_start, line_end))

        flush_paragraph()
        flush_table()
        flush_list()
        flush_code()
        return blocks, stack


def _detect_heading(line: str) -> tuple[int, str | None]:
    match = _MARKDOWN_HEADING_RE.match(line)
    if match:
        return len(match.group(1)), match.group(2).strip()
    # Avoid classifying ordinary short sentences as headings.
    if (
        len(line) <= 90
        and not line.endswith((".", ",", ";", ":", "!", "?"))
        and _PLAIN_HEADING_RE.match(line)
        and len(line.split()) <= 8
        and not _SENTENCE_HINT_RE.search(line)
        and not _LIST_RE.match(line)
    ):
        return 2, line
    return 1, None


def _looks_like_table_line(line: str) -> bool:
    if "|" in line and line.count("|") >= 2:
        return True
    if "\t" in line and len([part for part in line.split("\t") if part.strip()]) >= 2:
        return True
    return bool(re.search(r"\S+\s{2,}\S+\s{2,}\S+", line))
