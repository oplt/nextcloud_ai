from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import replace

import httpx

from ..core.config import settings
from .embedding_contract import (
    EmbeddingValidationError,
    active_embedding_fingerprint,
    cache_key_for_embedding,
    mean_pool_vectors,
    prepare_embedding_input,
    split_oversized_embedding_input,
    validate_embedding_vector,
)


class OllamaEmbeddingClient:
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        max_concurrency: int = 8,
        timeout_seconds: float = 60,
        expected_dim: int | None = None,
        cache_max_entries: int = 2048,
        max_input_chars: int | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.expected_dim = expected_dim or settings.EMBEDDING_DIM
        self.max_input_chars = max_input_chars or int(
            getattr(settings, "EMBEDDING_MAX_INPUT_CHARS", 24_000) or 24_000
        )
        self.fingerprint = replace(
            active_embedding_fingerprint(),
            model=self.model,
            dimension=self.expected_dim,
        )
        self._sem = asyncio.Semaphore(max_concurrency)
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_max = max(0, cache_max_entries)
        limits = httpx.Limits(
            max_connections=max_concurrency,
            max_keepalive_connections=max_concurrency,
            keepalive_expiry=30,
        )
        self._client = httpx.AsyncClient(timeout=timeout_seconds, limits=limits)

    def _cache_get(self, key: str) -> list[float] | None:
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return list(self._cache[key])

    def _cache_put(self, key: str, vector: list[float]) -> None:
        if self._cache_max <= 0:
            return
        self._cache[key] = list(vector)
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)

    async def _embed_via_modern_endpoint(
        self, input_payload: str | list[str]
    ) -> list[list[float]]:
        async with self._sem:
            response = await self._client.post(
                f"{self.base_url}/api/embed",
                json={
                    "model": self.model,
                    "input": input_payload,
                    "truncate": False,
                },
            )
        response.raise_for_status()
        payload = response.json()
        embeddings = payload.get("embeddings")
        if not isinstance(embeddings, list):
            raise EmbeddingValidationError(
                "Ollama /api/embed response missing embeddings"
            )
        if embeddings and not isinstance(embeddings[0], list):
            raise EmbeddingValidationError(
                "Ollama /api/embed returned malformed embeddings payload"
            )
        return embeddings

    async def _embed_via_legacy_endpoint(self, text: str) -> list[float]:
        async with self._sem:
            response = await self._client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
            )
        response.raise_for_status()
        payload = response.json()
        embedding = payload.get("embedding")
        if not isinstance(embedding, list):
            raise EmbeddingValidationError(
                "Ollama /api/embeddings response missing embedding"
            )
        return embedding

    def _parts_for_input(self, text: str) -> list[str]:
        """Prepare input; split explicitly when over the model char budget."""
        try:
            return [prepare_embedding_input(text, max_chars=self.max_input_chars)]
        except EmbeddingValidationError:
            return split_oversized_embedding_input(text, max_chars=self.max_input_chars)

    async def _embed_single_prepared(self, prepared: str) -> list[float]:
        key = cache_key_for_embedding(prepared, self.fingerprint)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        try:
            embeddings = await self._embed_via_modern_endpoint(prepared)
            if len(embeddings) != 1:
                raise EmbeddingValidationError(
                    f"embedding count mismatch: expected 1, got {len(embeddings)}"
                )
            vector = validate_embedding_vector(
                embeddings[0], expected_dim=self.expected_dim
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            vector = validate_embedding_vector(
                await self._embed_via_legacy_endpoint(prepared),
                expected_dim=self.expected_dim,
            )
        self._cache_put(key, vector)
        return vector

    async def _embed_text(self, text: str) -> list[float]:
        parts = self._parts_for_input(text)
        if len(parts) == 1:
            return await self._embed_single_prepared(parts[0])
        # Explicit split → embed parts → mean-pool (no silent truncation).
        part_vectors = [await self._embed_single_prepared(part) for part in parts]
        pooled = mean_pool_vectors(part_vectors)
        joined_key = cache_key_for_embedding("\n\n".join(parts), self.fingerprint)
        self._cache_put(joined_key, pooled)
        return pooled

    async def embed_query(self, text: str) -> list[float]:
        return await self._embed_text(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        # Resolve cache hits and classify single-part vs multi-part.
        single_indices: list[int] = []
        single_prepared: list[str] = []
        for index, text in enumerate(texts):
            parts = self._parts_for_input(text)
            if len(parts) > 1:
                results[index] = await self._embed_text(text)
                continue
            prepared = parts[0]
            key = cache_key_for_embedding(prepared, self.fingerprint)
            cached = self._cache_get(key)
            if cached is not None:
                results[index] = cached
            else:
                single_indices.append(index)
                single_prepared.append(prepared)

        if single_prepared:
            try:
                fresh = await self._embed_via_modern_endpoint(single_prepared)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                fresh = list(
                    await asyncio.gather(
                        *[
                            self._embed_via_legacy_endpoint(text)
                            for text in single_prepared
                        ]
                    )
                )
            if len(fresh) != len(single_prepared):
                raise EmbeddingValidationError(
                    f"embedding count mismatch: expected {len(single_prepared)}, "
                    f"got {len(fresh)}"
                )
            for slot, prepared, vector in zip(
                single_indices, single_prepared, fresh, strict=True
            ):
                validated = validate_embedding_vector(
                    vector, expected_dim=self.expected_dim
                )
                self._cache_put(
                    cache_key_for_embedding(prepared, self.fingerprint), validated
                )
                results[slot] = validated

        if any(item is None for item in results):
            raise EmbeddingValidationError(
                "embedding provider did not return a vector for every input"
            )
        return [list(item) for item in results if item is not None]

    async def aclose(self) -> None:
        await self._client.aclose()
