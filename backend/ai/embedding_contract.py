"""Embedding vector validation, fingerprinting, and batch helpers."""

from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from typing import Sequence

from ..core.config import settings

logger = logging.getLogger(__name__)

_IDENT_RE = re.compile(
    r"\b(?:[A-Z]{2,}[-_]?\d{2,}|\d{4,}[-/]\d+|INV[-_]?\w+|EUR|USD|GBP)\b",
    re.IGNORECASE,
)

# Shared preprocessor id — query and document paths must use the same value.
EMBEDDING_PREPROCESSOR_ID = "embed-input-v2"
DEFAULT_MAX_INPUT_CHARS = 24_000
DEFAULT_BATCH_MAX_CHARS = 96_000


class EmbeddingValidationError(ValueError):
    """Raised when an embedding vector fails contract checks."""


@dataclass(frozen=True, slots=True)
class EmbeddingFingerprint:
    provider: str
    model: str
    dimension: int
    preprocessor: str
    parser: str
    chunker: str

    def digest(self) -> str:
        payload = (
            f"{self.provider}|{self.model}|{self.dimension}|"
            f"{self.preprocessor}|{self.parser}|{self.chunker}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def compatible_with(self, other: "EmbeddingFingerprint") -> bool:
        """Same vector space only when provider/model/dim/preprocessor match.

        Matching dimension alone is not enough — do not mix model spaces.
        """
        return (
            self.provider == other.provider
            and self.model == other.model
            and self.dimension == other.dimension
            and self.preprocessor == other.preprocessor
        )


@dataclass(slots=True)
class EmbeddingCompatStatus:
    ready: bool
    provider: str
    model: str | None
    expected_dim: int
    observed_dim: int | None = None
    fingerprint: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "provider": self.provider,
            "model": self.model,
            "expected_dim": self.expected_dim,
            "observed_dim": self.observed_dim,
            "fingerprint": self.fingerprint,
            "error": self.error,
        }


def active_embedding_fingerprint(
    *,
    parser: str = "document_parser",
    chunker: str = "title-token-v2",
) -> EmbeddingFingerprint:
    provider = settings.effective_embedding_provider
    model = (
        settings.OLLAMA_EMBEDDING_MODEL if provider == "ollama" else "deterministic"
    )
    return EmbeddingFingerprint(
        provider=provider or "unknown",
        model=model,
        dimension=int(settings.EMBEDDING_DIM),
        preprocessor=EMBEDDING_PREPROCESSOR_ID,
        parser=parser,
        chunker=chunker,
    )


def validate_embedding_vector(
    vector: Sequence[float] | None,
    *,
    expected_dim: int,
    allow_zero: bool = False,
) -> list[float]:
    if vector is None:
        raise EmbeddingValidationError("embedding is None")
    if len(vector) != expected_dim:
        raise EmbeddingValidationError(
            f"embedding dimension mismatch: expected {expected_dim}, got {len(vector)}"
        )
    values = [float(v) for v in vector]
    if not all(math.isfinite(v) for v in values):
        raise EmbeddingValidationError("embedding contains non-finite values")
    if not allow_zero and all(v == 0.0 for v in values):
        raise EmbeddingValidationError("embedding is an all-zero vector")
    return values


def mean_pool_vectors(vectors: Sequence[Sequence[float]]) -> list[float]:
    if not vectors:
        raise EmbeddingValidationError("cannot mean-pool empty vector list")
    dim = len(vectors[0])
    if any(len(v) != dim for v in vectors):
        raise EmbeddingValidationError("mean-pool requires uniform dimensions")
    totals = [0.0] * dim
    for vector in vectors:
        for index, value in enumerate(vector):
            totals[index] += float(value)
    scale = 1.0 / len(vectors)
    pooled = [value * scale for value in totals]
    return validate_embedding_vector(pooled, expected_dim=dim)


def cache_key_for_embedding(text: str, fingerprint: EmbeddingFingerprint) -> str:
    body = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{fingerprint.digest()}:{body}"


def prepare_embedding_input(
    content: str, *, max_chars: int | None = None
) -> str:
    """Normalize text for embedding without destroying identifiers.

    Lexical search uses original chunk content. Embedding input may lightly
    normalize whitespace but keeps emails and ID-like tokens intact.
    Silent truncation is refused when ``max_chars`` is set; callers must split.
    Query and document paths share preprocessor id ``embed-input-v2``.
    """
    normalized = re.sub(r"[ \t]+", " ", content)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    if max_chars is not None and len(normalized) > max_chars:
        raise EmbeddingValidationError(
            f"embedding input length {len(normalized)} exceeds max_chars={max_chars}; "
            "split before embed"
        )
    return normalized


def split_oversized_embedding_input(
    content: str, *, max_chars: int
) -> list[str]:
    """Explicit split for model context limits (character budget)."""
    prepared = prepare_embedding_input(content)
    if len(prepared) <= max_chars:
        return [prepared]
    parts: list[str] = []
    start = 0
    while start < len(prepared):
        end = min(start + max_chars, len(prepared))
        if end < len(prepared):
            split_at = prepared.rfind(" ", start, end)
            if split_at > start + max_chars // 2:
                end = split_at
        part = prepared[start:end].strip()
        if part:
            parts.append(part)
        start = end if end > start else start + max_chars
    return parts or [prepared[:max_chars]]


def iter_embedding_batches(
    texts: Sequence[str],
    *,
    max_items: int = 32,
    max_chars: int = DEFAULT_BATCH_MAX_CHARS,
) -> list[tuple[int, list[str]]]:
    """Build batches by item count and approximate byte/char budget.

    Returns list of (start_index, batch_texts).
    """
    if max_items < 1:
        raise ValueError("max_items must be >= 1")
    batches: list[tuple[int, list[str]]] = []
    batch: list[str] = []
    batch_chars = 0
    start_index = 0
    for index, text in enumerate(texts):
        text_len = len(text)
        would_overflow = batch and (
            len(batch) >= max_items or batch_chars + text_len > max_chars
        )
        if would_overflow:
            batches.append((start_index, batch))
            batch = []
            batch_chars = 0
            start_index = index
        batch.append(text)
        batch_chars += text_len
    if batch:
        batches.append((start_index, batch))
    return batches


async def verify_embedding_runtime_compat() -> EmbeddingCompatStatus:
    """Probe the live embedding provider and confirm schema dimension match."""
    fingerprint = active_embedding_fingerprint()
    provider = fingerprint.provider
    status = EmbeddingCompatStatus(
        ready=False,
        provider=provider,
        model=fingerprint.model,
        expected_dim=fingerprint.dimension,
        fingerprint=fingerprint.digest(),
    )
    if provider == "deterministic":
        from .embedding_client import DeterministicEmbeddingClient

        client = DeterministicEmbeddingClient(dim=fingerprint.dimension)
        vector = await client.embed_query("embedding-dimension-probe")
        status.observed_dim = len(vector)
        status.ready = True
        return status

    if provider != "ollama":
        status.error = f"unsupported embedding provider: {provider}"
        return status

    from .ollama_embedding_client import OllamaEmbeddingClient

    client = OllamaEmbeddingClient(
        model=settings.OLLAMA_EMBEDDING_MODEL,
        base_url=str(settings.OLLAMA_BASE_URL),
        expected_dim=fingerprint.dimension,
        cache_max_entries=0,
    )
    try:
        vector = await client.embed_query("embedding-dimension-probe")
        status.observed_dim = len(vector)
        validate_embedding_vector(vector, expected_dim=fingerprint.dimension)
        status.ready = True
    except Exception as exc:
        status.error = str(exc)
        logger.warning("Embedding runtime compatibility check failed: %s", exc)
    finally:
        await client.aclose()
    return status
