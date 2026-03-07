from __future__ import annotations

import io

from backend.schemas.chat_schema import ChatSource

_PREAMBLE = (
    "You are a private company knowledge assistant.\n"
    "Answer only from the provided sources.\n"
    "If the sources are insufficient, say so clearly.\n"
    "Do not invent facts.\n"
    "Cite source numbers inline, for example [1] or [1][2].\n"
)


def build_grounded_prompt(question: str, sources: list[ChatSource]) -> str:
    buffer = io.StringIO()
    buffer.write(_PREAMBLE)
    buffer.write("\nQUESTION:\n")
    buffer.write(question)
    buffer.write("\n\nSOURCES:\n")

    for index, source in enumerate(sources, start=1):
        location_bits = []
        if source.page_number is not None:
            location_bits.append(f"page {source.page_number}")
        if source.section_title:
            location_bits.append(source.section_title)
        location = f" ({', '.join(location_bits)})" if location_bits else ""
        buffer.write(
            f"\n[SOURCE {index}] {source.file_name}{location}\n"
            f"Path: {source.file_path}\n"
            f"Excerpt: {source.snippet}\n"
        )

    buffer.write("\nFINAL ANSWER:\n")
    return buffer.getvalue()
