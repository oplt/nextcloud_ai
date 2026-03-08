from __future__ import annotations

import io
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
