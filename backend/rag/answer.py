from __future__ import annotations

from ..schemas.chat_schema import ChatSource


INSUFFICIENT_EVIDENCE_ANSWER = (
    "I could not verify this from the retrieved indexed sources. "
    "The available evidence is insufficient to answer without guessing."
)


def build_source_block(sources: list[ChatSource]) -> str:
    lines: list[str] = []
    for index, source in enumerate(sources, start=1):
        location_bits = []
        if source.page_number is not None:
            location_bits.append(f"page {source.page_number}")
        if source.section_title:
            location_bits.append(source.section_title)
        location = f" ({', '.join(location_bits)})" if location_bits else ""
        excerpt = source.content or source.snippet
        lines.append(
            f"[SOURCE {index}] {source.file_name}{location}\n"
            f"Path: {source.file_path}\n"
            f"Chunk ID: {source.chunk_id}\n"
            f"Excerpt: {excerpt}"
        )
    return "\n\n".join(lines)

