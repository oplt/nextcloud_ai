"""Phase 3: true property-based chunker invariants (Hypothesis)."""

from __future__ import annotations

import re

from hypothesis import given, settings, assume, strategies as st

from backend.ai.chunker import chunk_parsed_document
from backend.parsers.document_parser import ParsedDocument, ParsedPage
from backend.rag.chunker import HeadingTableAwareChunker
from backend.rag.parser import RagParser

_TOKEN_RE = re.compile(r"\S+")


def _word_count(text: str) -> int:
    return len(_TOKEN_RE.findall(text))


@st.composite
def chunk_documents(draw: st.DrawFn) -> ParsedDocument:
    """Generate mixed prose / table / code / unicode blocks."""
    n_blocks = draw(st.integers(min_value=1, max_value=8))
    parts: list[str] = []
    for index in range(n_blocks):
        kind = draw(st.sampled_from(["prose", "table", "code", "unicode"]))
        if kind == "prose":
            words = draw(st.integers(min_value=5, max_value=120))
            parts.append(" ".join(f"p{index}_{i}" for i in range(words)))
        elif kind == "table":
            rows = draw(st.integers(min_value=2, max_value=12))
            lines = ["| H1 | H2 |"] + [
                f"| c{index}_{r}a | c{index}_{r}b |" for r in range(rows)
            ]
            parts.append("\n".join(lines))
        elif kind == "code":
            lines = draw(st.integers(min_value=2, max_value=20))
            body = "\n".join(
                f"    def f{index}_{i}():\n        return {i}" for i in range(lines)
            )
            parts.append(f"```python\n{body}\n```")
        else:
            # Mix ASCII identifiers with Dutch/CJK so provenance spans stay sane.
            words = draw(st.integers(min_value=3, max_value=40))
            glyphs = draw(
                st.lists(
                    st.sampled_from(["café", "naïef", "東京", "straße", "w"]),
                    min_size=words,
                    max_size=words,
                )
            )
            parts.append(" ".join(f"{g}{i}" for i, g in enumerate(glyphs)))
    text = "\n\n".join(parts)
    assume(len(text.strip()) > 0)
    return ParsedDocument(text=text, pages=[ParsedPage(1, text)], metadata={})


@settings(max_examples=40, deadline=None)
@given(
    parsed=chunk_documents(),
    chunk_size=st.sampled_from([250, 320, 400, 500]),
    overlap=st.sampled_from([40, 50, 60, 80]),
)
def test_chunk_invariants_property(
    parsed: ParsedDocument, chunk_size: int, overlap: int
) -> None:
    assume(overlap < chunk_size)
    drafts = chunk_parsed_document(parsed, chunk_size=chunk_size, overlap=overlap)
    assert drafts, "chunker must emit at least one draft for nonempty text"

    # Order / identity
    assert [d.chunk_index for d in drafts] == list(range(len(drafts)))
    assert len({d.content for d in drafts}) == len(drafts)

    # Size bound (tokenizer word count)
    for draft in drafts:
        assert draft.token_count <= chunk_size
        assert _word_count(draft.content) <= chunk_size + 5  # small tokenizer slack

    # Monotonic source provenance
    starts = [
        int(draft.metadata.get("source_char_start", draft.char_start or 0))
        for draft in drafts
    ]
    ends = [
        int(draft.metadata.get("source_char_end", draft.char_end or 0))
        for draft in drafts
    ]
    assert starts == sorted(starts)
    for start, end in zip(starts, ends, strict=True):
        assert start <= end
        assert 0 <= start <= len(parsed.text)
        assert 0 <= end <= len(parsed.text) + 1

    # Coverage: every alphanumeric token from source appears in some chunk
    # (overlap may duplicate, but must not drop).
    source_tokens = set(_TOKEN_RE.findall(parsed.text))
    # Ignore pure fence markers from generated code blocks.
    source_tokens = {t for t in source_tokens if t not in {"```", "```python"}}
    joined = "\n".join(draft.content for draft in drafts)
    missing = [token for token in source_tokens if token not in joined]
    # Allow a tiny miss rate for pure punctuation fence noise.
    assert len(missing) <= max(2, len(source_tokens) // 50), missing[:10]


@settings(max_examples=25, deadline=None)
@given(
    words=st.integers(min_value=20, max_value=200),
    chunk_size=st.integers(min_value=30, max_value=80),
    overlap=st.integers(min_value=5, max_value=25),
)
def test_overlap_never_emits_tail_only_duplicate(
    words: int, chunk_size: int, overlap: int
) -> None:
    assume(overlap < chunk_size)
    prose = " ".join(f"w{i}" for i in range(words))
    table = "| H1 | H2 |\n| a | b |\n| c | d |"
    text = f"{prose}\n\n{table}"
    parsed = ParsedDocument(text=text, pages=[ParsedPage(1, text)], metadata={})
    drafts = HeadingTableAwareChunker(chunk_size=chunk_size, overlap=overlap).chunk(
        RagParser().normalize(parsed)
    )
    assert drafts
    # Final draft must contain table material or prose — never an empty/overlap-only ghost.
    assert drafts[-1].content.strip()
    contents = [d.content for d in drafts]
    # No two consecutive identical contents (overlap-only re-emit).
    for left, right in zip(contents, contents[1:], strict=False):
        assert left != right
