"""Phase 3 embeddings: validation, split/pool, batching, fingerprint reuse."""

from __future__ import annotations

import httpx
import json
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
from backend.ai.ollama_embedding_client import OllamaEmbeddingClient
from backend.core.config import Settings
from backend.core.security import AuthContext
from backend.ingestion.pipeline import _embed_in_batches
from backend.rag.stores import PgVectorStore
from backend.rag.scope import RetrievalScope


def test_validate_rejects_dim_nan_zero() -> None:
    with pytest.raises(EmbeddingValidationError):
        validate_embedding_vector([1.0], expected_dim=2)
    with pytest.raises(EmbeddingValidationError):
        validate_embedding_vector([float("nan"), 0.1], expected_dim=2)
    with pytest.raises(EmbeddingValidationError):
        validate_embedding_vector([0.0, 0.0], expected_dim=2)
    with pytest.raises(EmbeddingValidationError):
        validate_embedding_vector(["not-a-number", 0.1], expected_dim=2)


def test_production_ollama_requires_pinned_model_revision() -> None:
    with pytest.raises(ValueError, match="OLLAMA_EMBEDDING_MODEL_REVISION"):
        Settings(
            APP_ENV="production",
            AUTH_COOKIE_SECURE=True,
            EMBEDDING_PROVIDER="ollama",
            OLLAMA_EMBEDDING_MODEL_REVISION="unversioned",
            JWT_SECRET_KEY="a-sufficiently-long-jwt-secret",
            NEXTCLOUD_BRIDGE_SHARED_SECRET="a-sufficiently-long-bridge-secret",
            NEXTCLOUD_WEBHOOK_SECRET="a-sufficiently-long-webhook-secret",
            FIRST_SUPERUSER_PASSWORD="NotDefaultPass1!",
        )


def test_embedding_dimension_cannot_drift_from_pgvector_schema() -> None:
    with pytest.raises(ValueError, match="EMBEDDING_DIM"):
        Settings(EMBEDDING_DIM=768)


def test_embedding_tokenizer_id_cannot_drift_from_implementation() -> None:
    with pytest.raises(ValueError, match="EMBEDDING_TOKENIZER_ID"):
        Settings(EMBEDDING_TOKENIZER_ID="unimplemented-tokenizer")


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
    assert a.to_dict()["digest"] == a.digest()


def test_split_oversized_is_explicit_no_silent_truncate() -> None:
    text = "word " * 50
    with pytest.raises(EmbeddingValidationError):
        prepare_embedding_input(text, max_chars=20)
    parts = split_oversized_embedding_input(text, max_chars=40)
    assert len(parts) >= 2
    assert all(len(part) <= 40 for part in parts)
    assert "word" in parts[0]


def test_split_oversized_honors_utf8_byte_budget() -> None:
    parts = split_oversized_embedding_input("éé éé", max_chars=5)
    assert parts == ["éé", "éé"]
    assert all(len(part.encode("utf-8")) <= 5 for part in parts)


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
async def test_embed_in_batches_preserves_valid_slots_from_malformed_batch() -> None:
    class PartlyMalformed:
        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[0.1, 0.2], [float("nan"), 0.2]]

        async def embed_query(self, text: str) -> list[float]:
            return [0.1, 0.2]

    result = await _embed_in_batches(
        PartlyMalformed(),  # type: ignore[arg-type]
        ["valid", "invalid"],
        batch_size=2,
        expected_dim=2,
        max_retries=2,
    )
    assert result[0] == pytest.approx([0.1, 0.2])
    assert result[1] is None


@pytest.mark.asyncio
async def test_embed_in_batches_does_not_retry_non_transient_http_error() -> None:
    class BadRequest:
        calls = 0

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            self.calls += 1
            request = httpx.Request("POST", "http://ollama/api/embed")
            response = httpx.Response(400, request=request)
            raise httpx.HTTPStatusError(
                "bad request", request=request, response=response
            )

        async def embed_query(self, text: str) -> list[float]:
            return [0.1, 0.2]

    client = BadRequest()
    with pytest.raises(RuntimeError):
        await _embed_in_batches(
            client,  # type: ignore[arg-type]
            ["invalid request"],
            batch_size=1,
            expected_dim=2,
            max_retries=2,
        )
    assert client.calls == 1


@pytest.mark.asyncio
async def test_embed_in_batches_retries_transient_http_error() -> None:
    class TemporarilyUnavailable:
        calls = 0

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            self.calls += 1
            if self.calls == 1:
                request = httpx.Request("POST", "http://ollama/api/embed")
                response = httpx.Response(503, request=request)
                raise httpx.HTTPStatusError(
                    "unavailable", request=request, response=response
                )
            return [[0.1, 0.2] for _ in texts]

        async def embed_query(self, text: str) -> list[float]:
            return [0.1, 0.2]

    client = TemporarilyUnavailable()
    result = await _embed_in_batches(
        client,  # type: ignore[arg-type]
        ["retry me"],
        batch_size=1,
        expected_dim=2,
        max_retries=2,
    )
    assert result == [[0.1, 0.2]]
    assert client.calls == 2


@pytest.mark.asyncio
async def test_ollama_disables_provider_side_truncation() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    client = OllamaEmbeddingClient(
        model="test-model",
        base_url="http://ollama",
        expected_dim=2,
        cache_max_entries=0,
    )
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await client.embed_query("hello") == pytest.approx([0.1, 0.2])
    finally:
        await client.aclose()
    assert captured["truncate"] is False


@pytest.mark.asyncio
async def test_semantic_store_requires_active_embedding_fingerprint() -> None:
    class Repo:
        kwargs: dict[str, object] = {}

        async def semantic_search(self, **kwargs):
            self.kwargs = kwargs
            return []

    repo = Repo()
    await PgVectorStore(repo).search(  # type: ignore[arg-type]
        embedding=[0.1, 0.2],
        scope=RetrievalScope.resolve(
            auth=AuthContext(user_id="user", auth_provider="local", is_superuser=False)
        ),
        limit=5,
    )
    assert (
        repo.kwargs["embedding_fingerprint"] == active_embedding_fingerprint().digest()
    )


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
