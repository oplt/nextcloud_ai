from __future__ import annotations

import hashlib
from typing import Protocol

from backend.core.config import settings


class EmbeddingClientProtocol(Protocol):
    async def embed_query(self, text: str) -> list[float]: ...
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class SimpleDeterministicEmbeddingClient:
    """
    Placeholder embedding client for development only.

    Replace with Ollama embeddings or another local embedding model.
    The output dimension must match settings.EMBEDDING_DIM.
    """

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or settings.EMBEDDING_DIM

    def _text_to_vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed_bytes = (digest * ((self.dim // len(digest)) + 1))[: self.dim]

        values = []
        for b in seed_bytes:
            values.append((b / 255.0) * 2.0 - 1.0)

        # normalize
        norm = sum(v * v for v in values) ** 0.5
        if norm == 0:
            return [0.0] * self.dim
        return [v / norm for v in values]

    async def embed_query(self, text: str) -> list[float]:
        return self._text_to_vector(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._text_to_vector(text) for text in texts]