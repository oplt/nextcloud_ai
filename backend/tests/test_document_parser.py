import io
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from backend.parsers.document_parser import parse_document_bytes


def _zip_xml(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_parse_odp_extracts_slide_text() -> None:
    payload = _zip_xml(
        {
            "content.xml": """<?xml version="1.0"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body><office:presentation>
    <text:p>Quarterly roadmap</text:p>
    <text:p>Launch connector indexing</text:p>
  </office:presentation></office:body>
</office:document-content>"""
        }
    )

    parsed = await parse_document_bytes("deck.odp", None, payload)

    assert "Quarterly roadmap" in parsed.text
    assert parsed.metadata["parser"] == "odp-xml"


@pytest.mark.asyncio
async def test_parse_odp_strips_embedding_hostile_symbols() -> None:
    payload = _zip_xml(
        {
            "content.xml": """<?xml version="1.0"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body><office:presentation>
    <text:p>Simple presentation</text:p>
    <text:p>🖼 Add a picture!</text:p>
  </office:presentation></office:body>
</office:document-content>"""
        }
    )

    parsed = await parse_document_bytes("deck.odp", None, payload)

    assert "Add a picture!" in parsed.text
    assert "🖼" not in parsed.text


@pytest.mark.asyncio
async def test_parse_xlsx_extracts_rows() -> None:
    payload = _zip_xml(
        {
            "xl/sharedStrings.xml": """<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <si><t>Name</t></si><si><t>Total</t></si><si><t>De Watergroep</t></si>
</sst>""",
            "xl/worksheets/sheet1.xml": """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row>
    <row><c t="s"><v>2</v></c><c><v>190.04</v></c></row>
  </sheetData>
</worksheet>""",
        }
    )

    parsed = await parse_document_bytes("invoice.xlsx", None, payload)

    assert "De Watergroep" in parsed.text
    assert "190.04" in parsed.text
    assert parsed.metadata["parser"] == "xlsx-xml"


@pytest.mark.asyncio
async def test_parse_legacy_doc_uses_binary_text_fallback() -> None:
    parsed = await parse_document_bytes("legacy.doc", None, b"\x00Hello legacy document\x00")

    assert "Hello legacy document" in parsed.text
    assert parsed.metadata["fallback"] is True
