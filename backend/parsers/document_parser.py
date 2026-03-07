from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import docx
import pdfplumber


@dataclass(slots=True)
class ParsedPage:
    page_number: int | None
    text: str


@dataclass(slots=True)
class ParsedDocument:
    text: str
    pages: list[ParsedPage]
    metadata: dict[str, object]


class UnsupportedDocumentTypeError(ValueError):
    pass


PDF_MIME_TYPES = {"application/pdf"}
DOCX_MIME_TYPES = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
TEXT_MIME_TYPES = {"text/plain", "text/markdown", "text/x-markdown", "application/octet-stream"}


async def parse_document_bytes(file_name: str, mime_type: str | None, payload: bytes) -> ParsedDocument:
    suffix = Path(file_name).suffix.lower()
    normalized_mime = (mime_type or "").lower()

    if suffix == ".pdf" or normalized_mime in PDF_MIME_TYPES:
        return parse_pdf_bytes(payload)
    if suffix == ".docx" or normalized_mime in DOCX_MIME_TYPES:
        return parse_docx_bytes(payload)
    if suffix in {".txt", ".md", ".markdown"} or normalized_mime in TEXT_MIME_TYPES:
        return parse_text_bytes(payload, markdown=suffix in {".md", ".markdown"} or "markdown" in normalized_mime)
    raise UnsupportedDocumentTypeError(f"Unsupported document type for {file_name}")


def parse_pdf_bytes(payload: bytes) -> ParsedDocument:
    pages: list[ParsedPage] = []
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(ParsedPage(page_number=index, text=text))
    combined = "\n\n".join(page.text for page in pages)
    return ParsedDocument(text=combined, pages=pages, metadata={"page_count": len(pages), "parser": "pdfplumber"})


def parse_docx_bytes(payload: bytes) -> ParsedDocument:
    document = docx.Document(io.BytesIO(payload))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    text = "\n".join(paragraphs)
    pages = [ParsedPage(page_number=None, text=text)] if text else []
    return ParsedDocument(text=text, pages=pages, metadata={"paragraph_count": len(paragraphs), "parser": "python-docx"})


def parse_text_bytes(payload: bytes, *, markdown: bool = False) -> ParsedDocument:
    text = _decode_text(payload)
    pages = [ParsedPage(page_number=None, text=text)] if text.strip() else []
    return ParsedDocument(
        text=text,
        pages=pages,
        metadata={"parser": "plain-text", "markdown": markdown, "line_count": len(text.splitlines())},
    )


def _decode_text(payload: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="ignore")
