from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
import html
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
    attachments: list["ParsedAttachment"] = field(default_factory=list)


@dataclass(slots=True)
class ParsedAttachment:
    file_name: str
    mime_type: str | None
    payload: bytes
    is_inline: bool = False
    content_id: str | None = None


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
EMAIL_MIME_TYPES = {"message/rfc822", "application/eml"}

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
    if suffix == ".eml" or normalized_mime in EMAIL_MIME_TYPES:
        return parse_email_bytes(payload)
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


def parse_email_bytes(payload: bytes) -> ParsedDocument:
    message = BytesParser(policy=policy.default).parsebytes(payload)
    body = _extract_email_body(message)
    attachments = _extract_email_attachments(message)

    subject = _clean_header(message.get("Subject"))
    sender = _format_addresses(message.get_all("From", []))
    recipients = _format_addresses(
        [*message.get_all("To", []), *message.get_all("Cc", [])]
    )
    sent_at = _normalize_email_datetime(message.get("Date"))
    message_id = _clean_header(message.get("Message-ID"))
    references = [
        ref
        for ref in re.split(r"\s+", _clean_header(message.get("References")))
        if ref
    ]
    in_reply_to = _clean_header(message.get("In-Reply-To"))
    thread_key = references[0] if references else (in_reply_to or message_id)

    attachment_lines = [
        f"- {attachment.file_name} ({attachment.mime_type or 'application/octet-stream'})"
        for attachment in attachments
    ]
    sections = [
        line
        for line in [
            f"Subject: {subject}" if subject else "",
            f"From: {sender}" if sender else "",
            f"To: {recipients}" if recipients else "",
            f"Date: {sent_at}" if sent_at else "",
            body.strip(),
            "Attachments:\n" + "\n".join(attachment_lines) if attachment_lines else "",
        ]
        if line
    ]
    text = "\n\n".join(sections).strip()
    pages = [ParsedPage(page_number=None, text=text)] if text else []
    return ParsedDocument(
        text=text,
        pages=pages,
        metadata={
            "parser": "email-rfc822",
            "subject": subject,
            "from": sender,
            "to": recipients,
            "date": sent_at,
            "message_id": message_id,
            "in_reply_to": in_reply_to,
            "references": references,
            "thread_key": thread_key,
            "attachment_count": len(attachments),
            "attachments": [
                {
                    "file_name": attachment.file_name,
                    "mime_type": attachment.mime_type,
                    "size_bytes": len(attachment.payload),
                    "is_inline": attachment.is_inline,
                }
                for attachment in attachments
            ],
        },
        attachments=attachments,
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


def _extract_email_body(message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if message.is_multipart():
        for part in message.walk():
            if part.is_multipart():
                continue
            disposition = (part.get_content_disposition() or "").lower()
            if disposition == "attachment":
                continue
            content_type = part.get_content_type().lower()
            text = _decode_message_part(part)
            if not text.strip():
                continue
            if content_type == "text/plain":
                plain_parts.append(text.strip())
            elif content_type == "text/html":
                html_parts.append(_strip_html(text).strip())
    else:
        text = _decode_message_part(message)
        if message.get_content_type().lower() == "text/html":
            html_parts.append(_strip_html(text).strip())
        else:
            plain_parts.append(text.strip())

    candidate_parts = plain_parts or html_parts
    return "\n\n".join(part for part in candidate_parts if part).strip()


def _extract_email_attachments(message) -> list[ParsedAttachment]:
    attachments: list[ParsedAttachment] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        file_name = part.get_filename()
        if disposition != "attachment" and not file_name:
            continue
        payload = part.get_payload(decode=True) or b""
        if not payload:
            continue
        attachments.append(
            ParsedAttachment(
                file_name=file_name or f"attachment-{len(attachments) + 1}",
                mime_type=part.get_content_type(),
                payload=payload,
                is_inline=disposition == "inline",
                content_id=_clean_header(part.get("Content-ID")),
            )
        )
    return attachments


def _decode_message_part(part) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw_payload = part.get_payload()
        return raw_payload if isinstance(raw_payload, str) else ""
    charset = part.get_content_charset()
    if charset:
        try:
            return payload.decode(charset)
        except (LookupError, UnicodeDecodeError):
            pass
    return _decode_text(payload)


def _strip_html(value: str) -> str:
    collapsed = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    collapsed = re.sub(r"(?i)<br\s*/?>", "\n", collapsed)
    collapsed = re.sub(r"(?i)</p>", "\n", collapsed)
    collapsed = re.sub(r"(?s)<[^>]+>", " ", collapsed)
    collapsed = html.unescape(collapsed)
    collapsed = re.sub(r"[ \t]+", " ", collapsed)
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
    return collapsed.strip()


def _clean_header(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(str(value).split())


def _format_addresses(values: list[str]) -> str:
    addresses = []
    for name, address in getaddresses(values):
        name = name.strip()
        address = address.strip()
        if name and address:
            addresses.append(f"{name} <{address}>")
        elif address:
            addresses.append(address)
        elif name:
            addresses.append(name)
    return ", ".join(addresses)


def _normalize_email_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError, IndexError):
        return _clean_header(value) or None
