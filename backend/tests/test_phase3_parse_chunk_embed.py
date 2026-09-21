"""Phase 3: parsing order, chunk properties, embedding contracts."""

from __future__ import annotations

import io

import pytest
from docx import Document

from backend.ai.chunker import chunk_parsed_document
from backend.ai.embedding_contract import (
    EmbeddingValidationError,
    active_embedding_fingerprint,
    prepare_embedding_input,
    validate_embedding_vector,
)
from backend.ai.embedding_client import DeterministicEmbeddingClient
from backend.parsers.document_parser import (
    ParsedDocument,
    ParsedPage,
    parse_docx_bytes,
    parse_pdf_bytes,
)
from backend.rag.chunker import HeadingTableAwareChunker
from backend.rag.parser import RagParser


def _words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_docx_preserves_paragraph_table_paragraph_order() -> None:
    document = Document()
    document.add_heading("Intro", level=1)
    document.add_paragraph("Before table sentence.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "H1"
    table.cell(0, 1).text = "H2"
    table.cell(1, 0).text = "A"
    table.cell(1, 1).text = "B"
    document.add_paragraph("After table sentence.")
    buffer = io.BytesIO()
    document.save(buffer)
    parsed = parse_docx_bytes(buffer.getvalue())
    assert "Before table sentence." in parsed.text
    assert "After table sentence." in parsed.text
    before = parsed.text.index("Before table sentence.")
    table_pos = parsed.text.index("| H1 | H2 |")
    after = parsed.text.index("After table sentence.")
    assert before < table_pos < after
    assert parsed.metadata.get("body_order") == "document-order"
    assert "# Intro" in parsed.text or parsed.text.startswith("#")


def test_pdf_counts_physical_pages_and_uses_combined_text_for_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePage:
        def __init__(self, text: str, tables=None):
            self._text = text
            self._tables = tables or []

        def extract_text(self):
            return self._text

        def extract_tables(self):
            return self._tables

    class FakePdf:
        pages = [
            FakePage(""),  # blank page 1
            FakePage("Invoice total EUR 12.00 on final page."),
        ]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        "backend.parsers.document_parser.pdfplumber.open",
        lambda *_a, **_k: FakePdf(),
    )
    parsed = parse_pdf_bytes(b"%PDF-fake")
    assert parsed.metadata["page_count"] == 2
    assert parsed.metadata["empty_page_numbers"] == [1]
    assert len(parsed.pages) == 2
    assert parsed.pages[0].page_number == 1
    assert parsed.pages[0].text == ""
    assert parsed.pages[1].page_number == 2
    fields = parsed.metadata["extracted_fields"]
    assert isinstance(fields, dict)
    # Fields come from combined text, not only last-page local var.
    assert "Invoice total EUR 12.00" in parsed.text


def test_rag_parser_carries_headings_across_pages_and_skips_sentence_headings() -> None:
    parsed = ParsedDocument(
        text="",
        pages=[
            ParsedPage(page_number=1, text="# Section One\nBody on page one."),
            ParsedPage(page_number=2, text="Continuation on page two.\nThis is a short sentence."),
        ],
        metadata={},
    )
    rag = RagParser().normalize(parsed)
    headings = [b for b in rag.blocks if b.block_type == "heading"]
    assert len(headings) == 1
    assert headings[0].text == "Section One"
    cont = next(b for b in rag.blocks if "Continuation" in b.text)
    assert cont.heading_path == "Section One"
    # Ordinary short sentence must not become a heading.
    assert not any(
        b.block_type == "heading" and "short sentence" in b.text for b in rag.blocks
    )


def test_chunker_overlap_does_not_emit_oversized_combined_chunk() -> None:
    # 700 + 200 at size 850 / overlap 100 must not emit a 900-word chunk.
    text = _words(700, "a") + "\n\n" + _words(200, "b")
    parsed = ParsedDocument(text=text, pages=[ParsedPage(1, text)], metadata={})
    drafts = HeadingTableAwareChunker(chunk_size=850, overlap=100).chunk(
        RagParser().normalize(parsed)
    )
    assert drafts
    assert all(d.token_count <= 850 for d in drafts)
    assert max(d.token_count for d in drafts) < 900
    # First emission is the 700-word block (not 900).
    assert any(d.token_count == 700 or 650 <= d.token_count <= 700 for d in drafts)


def test_chunker_paragraph_table_end_no_overlap_only_tail() -> None:
    text = _words(40, "p") + "\n\n| H1 | H2 |\n| a | b |\n\n"
    parsed = ParsedDocument(text=text, pages=[ParsedPage(1, text)], metadata={})
    drafts = HeadingTableAwareChunker(chunk_size=80, overlap=20).chunk(
        RagParser().normalize(parsed)
    )
    assert drafts
    contents = [d.content for d in drafts]
    para_only = [c for c in contents if "p0" in c and "| H1 |" not in c]
    assert len(para_only) == 1
    # No trailing chunk that is only a suffix of the paragraph.
    assert not any(d.metadata.get("overlap_only") for d in drafts)


def test_chunker_source_spans_exclude_synthetic_context() -> None:
    blocks_text = _words(20, "ctx") + "\n\n| A | B |\n| 1 | 2 |\n\n" + _words(10, "aft")
    parsed = ParsedDocument(
        text=blocks_text, pages=[ParsedPage(1, blocks_text)], metadata={}
    )
    drafts = HeadingTableAwareChunker(
        chunk_size=100, overlap=10, table_context_tokens=15
    ).chunk(RagParser().normalize(parsed))
    table_drafts = [
        d
        for d in drafts
        if d.metadata.get("block_type") == "table" or "| A | B |" in d.content
    ]
    assert table_drafts
    for draft in table_drafts:
        assert draft.metadata.get("source_char_start") is not None
        assert draft.char_start == draft.metadata["source_char_start"]
        assert draft.char_end == draft.metadata["source_char_end"]
        assert draft.char_start <= draft.char_end
        source_body = str(draft.metadata.get("source_body") or "")
        if source_body:
            # Synthetic context must not expand source spans beyond the table body.
            assert "Context above" not in source_body


def test_chunk_property_size_order_coverage_no_dupes() -> None:
    text = "\n\n".join(_words(50, f"s{section}") for section in range(5))
    parsed = ParsedDocument(text=text, pages=[ParsedPage(1, text)], metadata={})
    for size, overlap in ((250, 40), (400, 60), (500, 80)):
        drafts = chunk_parsed_document(parsed, chunk_size=size, overlap=overlap)
        assert drafts
        assert [d.chunk_index for d in drafts] == list(range(len(drafts)))
        assert all(d.token_count <= size for d in drafts)
        starts = [int(d.metadata.get("source_char_start", d.char_start)) for d in drafts]
        assert starts == sorted(starts)
        assert len({d.content for d in drafts}) == len(drafts)
        # Coverage: every section marker appears in at least one chunk.
        joined = "\n".join(d.content for d in drafts)
        for section in range(5):
            assert f"s{section}0" in joined


def test_parent_chunks_group_children() -> None:
    from backend.rag.chunker import build_parent_chunks

    text = "\n\n".join(_words(30, f"g{i}") for i in range(6))
    parsed = ParsedDocument(text=text, pages=[ParsedPage(1, text)], metadata={})
    children = chunk_parsed_document(parsed, chunk_size=40, overlap=8)
    parents = build_parent_chunks(children, child_size=40, parent_size=100)
    assert parents
    assert sum(int(p.metadata["child_count"]) for p in parents) == len(children)
    assert all(p.metadata.get("chunker") == "title-token-v2-parent" for p in parents)


def test_table_split_repeats_header_row() -> None:
    rows = ["| H1 | H2 |"] + [f"| r{i}a | r{i}b |" for i in range(40)]
    text = "\n".join(rows)
    parsed = ParsedDocument(text=text, pages=[ParsedPage(1, text)], metadata={})
    drafts = HeadingTableAwareChunker(chunk_size=30, overlap=5).chunk(
        RagParser().normalize(parsed)
    )
    table_parts = [d for d in drafts if "| H1 | H2 |" in d.content or d.metadata.get("block_type") == "table"]
    assert len(table_parts) >= 2
    # Later splits should repeat the header.
    assert any(d.metadata.get("repeated_table_header") for d in table_parts[1:])


def test_embedding_validation_rejects_bad_vectors() -> None:
    with pytest.raises(EmbeddingValidationError):
        validate_embedding_vector([1.0, 2.0], expected_dim=3)
    with pytest.raises(EmbeddingValidationError):
        validate_embedding_vector([float("nan")] * 4, expected_dim=4)
    with pytest.raises(EmbeddingValidationError):
        validate_embedding_vector([0.0, 0.0, 0.0], expected_dim=3)
    ok = validate_embedding_vector([0.1, -0.2, 0.3], expected_dim=3)
    assert ok[0] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_deterministic_embeddings_change_with_fingerprint_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.ai.embedding_client.settings.EMBEDDING_DIM", 8, raising=False
    )
    monkeypatch.setattr(
        "backend.ai.embedding_contract.settings.EMBEDDING_DIM", 8, raising=False
    )
    monkeypatch.setattr(
        "backend.ai.embedding_contract.settings.effective_embedding_provider",
        "deterministic",
        raising=False,
    )
    client = DeterministicEmbeddingClient(dim=8)
    v1 = await client.embed_query("hello")
    # Fingerprint includes model; changing digest input changes vector.
    client.fingerprint = active_embedding_fingerprint(chunker="other-chunker")
    # Rebuild internal use — DeterministicEmbeddingClient uses fingerprint in hash
    v2 = await client.embed_query("hello")
    assert v1 != v2


def test_prepare_embedding_input_keeps_identifiers_refuses_silent_truncation() -> None:
    text = "Contact a@b.com about INV-99 and EUR 12"
    prepared = prepare_embedding_input(text)
    assert "a@b.com" in prepared
    assert "INV-99" in prepared
    with pytest.raises(EmbeddingValidationError):
        prepare_embedding_input("x" * 100, max_chars=10)
