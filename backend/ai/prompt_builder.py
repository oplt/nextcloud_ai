from __future__ import annotations

import io

from backend.schemas.chat_schema import ChatSource

_PREAMBLE = (
    "You are a private company knowledge assistant.\n"
    "Answer ONLY from the provided sources.\n"
    "If the sources are insufficient, say so clearly.\n"
    "Do not invent facts.\n"
    "Prefer precise and concise answers.\n"
    "When relevant, mention which source numbers support each point.\n"
)


def build_grounded_prompt(question: str, sources: list[ChatSource]) -> str:
    buf = io.StringIO()
    buf.write(_PREAMBLE)
    buf.write("\nQUESTION:\n")
    buf.write(question)
    buf.write("\n\nSOURCES:\n")

    for idx, src in enumerate(sources, start=1):
        parts = []
        if src.page_number is not None:
            parts.append(f"page {src.page_number}")
        if src.section_title:
            parts.append(f"section {src.section_title}")

        location_str = f" ({', '.join(parts)})" if parts else ""

        buf.write(
            f"\n[SOURCE {idx}] {src.file_name}{location_str}\n"
            f"Path: {src.file_path}\n"
            f"Excerpt: {src.snippet}\n"
        )

    buf.write("\nFINAL ANSWER:\n")
    return buf.getvalue()