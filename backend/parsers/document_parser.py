from __future__ import annotations

import pdfplumber
import docx


async def parse_pdf(path: str) -> str:

    text_parts = []

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text()
            if txt:
                text_parts.append(txt)

    return "\n".join(text_parts)


async def parse_docx(path: str) -> str:

    doc = docx.Document(path)

    return "\n".join([p.text for p in doc.paragraphs])


async def parse_txt(path: str) -> str:

    with open(path, "r", encoding="utf-8") as f:
        return f.read()