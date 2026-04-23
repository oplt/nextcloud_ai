from __future__ import annotations

import io
from email.message import EmailMessage
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from backend.parsers.document_parser import parse_document_bytes


@pytest.mark.asyncio
async def test_parse_document_bytes_supports_odt_by_extension() -> None:
    parsed = await parse_document_bytes("report.odt", None, _build_odt_payload())

    assert parsed.text == (
        "Quarterly Report\n"
        "Hello team.\n"
        "Line one\n"
        "Line two\n"
        "Keep  spacing"
    )
    assert parsed.pages[0].text == parsed.text
    assert parsed.metadata == {"block_count": 4, "parser": "odt-xml"}


@pytest.mark.asyncio
async def test_parse_document_bytes_supports_odt_by_mime_type() -> None:
    parsed = await parse_document_bytes(
        "report",
        "application/vnd.oasis.opendocument.text",
        _build_odt_payload(),
    )

    assert parsed.text.startswith("Quarterly Report\nHello team.")
    assert parsed.metadata["parser"] == "odt-xml"


@pytest.mark.asyncio
async def test_parse_document_bytes_supports_eml_with_attachments() -> None:
    message = EmailMessage()
    message["Subject"] = "Weekly Team Sync"
    message["From"] = "Alice Example <alice@example.com>"
    message["To"] = "Bob Example <bob@example.com>"
    message["Message-ID"] = "<msg-1@example.com>"
    message["References"] = "<thread-root@example.com>"
    message.set_content("Decision: Ship the pilot this week.\nAction item: Alice to send rollout plan by 2026-05-01.")
    message.add_attachment(
        b"Contract renewal date is 2026-06-30.",
        maintype="text",
        subtype="plain",
        filename="renewal.txt",
    )

    parsed = await parse_document_bytes(
        "weekly-sync.eml",
        "message/rfc822",
        message.as_bytes(),
    )

    assert "Weekly Team Sync" in parsed.text
    assert "Ship the pilot this week" in parsed.text
    assert parsed.metadata["thread_key"] == "<thread-root@example.com>"
    assert parsed.metadata["attachment_count"] == 1
    assert parsed.attachments[0].file_name == "renewal.txt"
    assert parsed.attachments[0].payload == b"Contract renewal date is 2026-06-30."


def _build_odt_payload() -> bytes:
    content_xml = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    office:version="1.2">
  <office:body>
    <office:text>
      <text:h text:outline-level="1">Quarterly Report</text:h>
      <text:p>Hello <text:span>team</text:span>.</text:p>
      <text:p>Line one<text:line-break/>Line two</text:p>
      <text:p>Keep<text:s text:c="2"/>spacing</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "mimetype", "application/vnd.oasis.opendocument.text", compress_type=0
        )
        archive.writestr("content.xml", content_xml)
    return buffer.getvalue()
