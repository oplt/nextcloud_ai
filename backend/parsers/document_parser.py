from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

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
DOCX_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
}
ODT_MIME_TYPES = {"application/vnd.oasis.opendocument.text"}
TEXT_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "application/octet-stream",
}

ODT_OFFICE_NS = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
ODT_TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
ODT_DOCUMENT_CONTENT_TAG = f"{{{ODT_OFFICE_NS}}}document-content"
ODT_PARAGRAPH_TAG = f"{{{ODT_TEXT_NS}}}p"
ODT_HEADING_TAG = f"{{{ODT_TEXT_NS}}}h"
ODT_LINE_BREAK_TAG = f"{{{ODT_TEXT_NS}}}line-break"
ODT_TAB_TAG = f"{{{ODT_TEXT_NS}}}tab"
ODT_SPACE_TAG = f"{{{ODT_TEXT_NS}}}s"


async def parse_document_bytes(
    file_name: str, mime_type: str | None, payload: bytes
) -> ParsedDocument:
    suffix = Path(file_name).suffix.lower()
    normalized_mime = (mime_type or "").lower()

    if suffix == ".pdf" or normalized_mime in PDF_MIME_TYPES:
        return parse_pdf_bytes(payload)
    if suffix == ".docx" or normalized_mime in DOCX_MIME_TYPES:
        return parse_docx_bytes(payload)
    if suffix == ".odt" or normalized_mime in ODT_MIME_TYPES:
        return parse_odt_bytes(payload)
    if suffix in {".txt", ".md", ".markdown"} or normalized_mime in TEXT_MIME_TYPES:
        return parse_text_bytes(
            payload,
            markdown=suffix in {".md", ".markdown"} or "markdown" in normalized_mime,
        )
    raise UnsupportedDocumentTypeError(f"Unsupported document type for {file_name}")


def parse_pdf_bytes(payload: bytes) -> ParsedDocument:
    pages: list[ParsedPage] = []
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(ParsedPage(page_number=index, text=text))
    combined = "\n\n".join(page.text for page in pages)
    return ParsedDocument(
        text=combined,
        pages=pages,
        metadata={"page_count": len(pages), "parser": "pdfplumber"},
    )


def parse_docx_bytes(payload: bytes) -> ParsedDocument:
    document = docx.Document(io.BytesIO(payload))
    paragraphs = [
        paragraph.text.strip()
        for paragraph in document.paragraphs
        if paragraph.text.strip()
    ]
    text = "\n".join(paragraphs)
    pages = [ParsedPage(page_number=None, text=text)] if text else []
    return ParsedDocument(
        text=text,
        pages=pages,
        metadata={"paragraph_count": len(paragraphs), "parser": "python-docx"},
    )


def parse_odt_bytes(payload: bytes) -> ParsedDocument:
    try:
        with ZipFile(io.BytesIO(payload)) as archive:
            content_xml = archive.read("content.xml")
    except (BadZipFile, KeyError) as exc:
        raise ValueError("Invalid ODT payload") from exc

    try:
        root = ET.fromstring(content_xml)
    except ET.ParseError as exc:
        raise ValueError("Invalid ODT XML payload") from exc

    if root.tag != ODT_DOCUMENT_CONTENT_TAG:
        raise ValueError("Invalid ODT document root")

    document_text = root.find(f"./{{{ODT_OFFICE_NS}}}body/{{{ODT_OFFICE_NS}}}text")
    if document_text is None:
        raise ValueError("Invalid ODT document body")

    blocks = [
        block_text
        for element in document_text.iter()
        if element.tag in {ODT_PARAGRAPH_TAG, ODT_HEADING_TAG}
        if (block_text := _extract_odt_text(element))
    ]
    text = "\n".join(blocks)
    pages = [ParsedPage(page_number=None, text=text)] if text else []
    return ParsedDocument(
        text=text,
        pages=pages,
        metadata={"block_count": len(blocks), "parser": "odt-xml"},
    )


def parse_text_bytes(payload: bytes, *, markdown: bool = False) -> ParsedDocument:
    text = _decode_text(payload)
    pages = [ParsedPage(page_number=None, text=text)] if text.strip() else []
    return ParsedDocument(
        text=text,
        pages=pages,
        metadata={
            "parser": "plain-text",
            "markdown": markdown,
            "line_count": len(text.splitlines()),
        },
    )


def _decode_text(payload: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="ignore")


def _extract_odt_text(element: ET.Element) -> str:
    parts: list[str] = []
    if element.text:
        parts.append(element.text)

    for child in element:
        if child.tag == ODT_LINE_BREAK_TAG:
            parts.append("\n")
        elif child.tag == ODT_TAB_TAG:
            parts.append("\t")
        elif child.tag == ODT_SPACE_TAG:
            count = int(child.attrib.get(f"{{{ODT_TEXT_NS}}}c", "1"))
            parts.append(" " * max(1, count))
        else:
            parts.append(_extract_odt_text(child))

        if child.tail:
            parts.append(child.tail)

    return "".join(parts).strip()
