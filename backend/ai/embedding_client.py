from __future__ import annotations

import hashlib
from typing import Protocol

from ..core.config import settings
from .ollama_embedding_client import OllamaEmbeddingClient


class EmbeddingClientProtocol(Protocol):
    async def embed_query(self, text: str) -> list[float]: ...
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class DeterministicEmbeddingClient:
    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or settings.EMBEDDING_DIM

    def _text_to_vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed_bytes = (digest * ((self.dim // len(digest)) + 1))[: self.dim]
        values = [((value / 255.0) * 2.0) - 1.0 for value in seed_bytes]
        norm = sum(value * value for value in values) ** 0.5
        if norm == 0:
            return [0.0] * self.dim
        return [value / norm for value in values]

    async def embed_query(self, text: str) -> list[float]:
        return self._text_to_vector(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._text_to_vector(text) for text in texts]


class EmbeddingProviderNotConfiguredError(RuntimeError):
    pass


class EmbeddingClientFactory:
    @staticmethod
    def create(*, allow_deterministic: bool = False) -> EmbeddingClientProtocol:
        if settings.effective_embedding_provider == "ollama":
            return OllamaEmbeddingClient(
                model=settings.OLLAMA_EMBEDDING_MODEL,
                base_url=str(settings.OLLAMA_BASE_URL),
            )
        if settings.effective_embedding_provider == "deterministic" and allow_deterministic:
            return DeterministicEmbeddingClient()
        raise EmbeddingProviderNotConfiguredError(
            "EMBEDDING_PROVIDER must be set to a real embedding provider. "
            "Set EMBEDDING_PROVIDER=ollama and configure OLLAMA_EMBEDDING_MODEL."
        )


def embedding_provider_health() -> dict[str, object]:
    provider = settings.effective_embedding_provider
    return {
        "provider": provider,
        "model": settings.OLLAMA_EMBEDDING_MODEL if provider == "ollama" else None,
        "dimension": settings.EMBEDDING_DIM,
        "real_embeddings": provider == "ollama",
    }
