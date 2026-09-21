"""Phase 3 embeddings: validation, split/pool, batching, fingerprint reuse."""

from __future__ import annotations

import pytest

from backend.ai.embedding_client import DeterministicEmbeddingClient
from backend.ai.embedding_contract import (
    EmbeddingFingerprint,
    EmbeddingValidationError,
    active_embedding_fingerprint,
    iter_embedding_batches,
    mean_pool_vectors,
    prepare_embedding_input,
    split_oversized_embedding_input,
    validate_embedding_vector,
)
from backend.ingestion.pipeline import _embed_in_batches


def test_validate_rejects_dim_nan_zero() -> None:
    with pytest.raises(EmbeddingValidationError):
        validate_embedding_vector([1.0], expected_dim=2)
    with pytest.raises(EmbeddingValidationError):
        validate_embedding_vector([float("nan"), 0.1], expected_dim=2)
    with pytest.raises(EmbeddingValidationError):
        validate_embedding_vector([0.0, 0.0], expected_dim=2)


def test_fingerprint_compatible_requires_model_not_just_dim() -> None:
    a = EmbeddingFingerprint(
        provider="ollama",
        model="bge-m3:latest",
        dimension=1024,
        preprocessor="embed-input-v2",
        parser="pdf",
        chunker="title-token-v2",
    )
    b = EmbeddingFingerprint(
        provider="ollama",
        model="other-model",
        dimension=1024,
        preprocessor="embed-input-v2",
        parser="pdf",
        chunker="title-token-v2",
    )
    assert a.compatible_with(a)
    assert not a.compatible_with(b)
    assert a.digest() != b.digest()


def test_split_oversized_is_explicit_no_silent_truncate() -> None:
    text = "word " * 50
    with pytest.raises(EmbeddingValidationError):
        prepare_embedding_input(text, max_chars=20)
    parts = split_oversized_embedding_input(text, max_chars=40)
    assert len(parts) >= 2
    assert all(len(part) <= 40 for part in parts)
    assert "word" in parts[0]


def test_mean_pool_and_batch_budget() -> None:
    pooled = mean_pool_vectors([[1.0, 3.0], [3.0, 1.0]])
    assert pooled == pytest.approx([2.0, 2.0])
    texts = ["a" * 10, "b" * 10, "c" * 10, "d" * 10]
    batches = iter_embedding_batches(texts, max_items=2, max_chars=25)
    assert len(batches) == 2
    assert batches[0][0] == 0
    assert len(batches[0][1]) == 2
    # Char budget forces earlier split than max_items alone.
    tight = iter_embedding_batches(texts, max_items=10, max_chars=15)
    assert len(tight) == 4


def test_prepare_keeps_email_and_invoice_ids() -> None:
    text = "Email a@b.com about INV-42 for EUR 99"
    prepared = prepare_embedding_input(text)
    assert "a@b.com" in prepared
    assert "INV-42" in prepared
    assert "EUR" in prepared


@pytest.mark.asyncio
async def test_embed_in_batches_preserves_earlier_success() -> None:
    class Flaky:
        def __init__(self) -> None:
            self.calls = 0

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            self.calls += 1
            if self.calls == 1:
                return [[0.1, 0.2, 0.3] for _ in texts]
            raise RuntimeError("provider down")

        async def embed_query(self, text: str) -> list[float]:
            return [0.1, 0.2, 0.3]

    client = Flaky()
    # Two batches of 1 → first succeeds, second fails; preserve first.
    result = await _embed_in_batches(
        client,  # type: ignore[arg-type]
        ["one", "two"],
        batch_size=1,
        expected_dim=3,
        max_retries=0,
        max_batch_chars=10_000,
    )
    assert result[0] == pytest.approx([0.1, 0.2, 0.3])
    assert result[1] is None


@pytest.mark.asyncio
async def test_deterministic_vectors_change_when_fingerprint_changes(
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
    first = await client.embed_query("same")
    client.fingerprint = active_embedding_fingerprint(chunker="other")
    second = await client.embed_query("same")
    assert first != second
