from __future__ import annotations

import asyncio

import httpx


class OllamaEmbeddingClient:
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        max_concurrency: int = 8,
        timeout_seconds: float = 60,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._sem = asyncio.Semaphore(max_concurrency)
        limits = httpx.Limits(
            max_connections=max_concurrency,
            max_keepalive_connections=max_concurrency,
            keepalive_expiry=30,
        )
        self._client = httpx.AsyncClient(timeout=timeout_seconds, limits=limits)

    async def _embed_via_modern_endpoint(
        self, input_payload: str | list[str]
    ) -> list[list[float]]:
        async with self._sem:
            response = await self._client.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": input_payload},
            )
        response.raise_for_status()
        payload = response.json()
        embeddings = payload.get("embeddings")
        if not isinstance(embeddings, list):
            raise ValueError("Ollama /api/embed response missing embeddings")
        if embeddings and not isinstance(embeddings[0], list):
            raise ValueError("Ollama /api/embed returned malformed embeddings payload")
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
            raise ValueError("Ollama /api/embeddings response missing embedding")
        return embedding

    async def embed_query(self, text: str) -> list[float]:
        try:
            embeddings = await self._embed_via_modern_endpoint(text)
            if not embeddings:
                raise ValueError("Ollama /api/embed returned empty embeddings")
            return embeddings[0]
        except httpx.HTTPStatusError as exc:
            # Backward compatibility with older Ollama versions that still expose /api/embeddings.
            if exc.response.status_code != 404:
                raise
            return await self._embed_via_legacy_endpoint(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            return await self._embed_via_modern_endpoint(texts)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            return list(await asyncio.gather(*[self._embed_via_legacy_endpoint(text) for text in texts]))

    async def aclose(self) -> None:
        await self._client.aclose()
