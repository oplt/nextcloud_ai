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

    async def embed_query(self, text: str) -> list[float]:
        async with self._sem:
            response = await self._client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
            )
        response.raise_for_status()
        return response.json()["embedding"]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return list(await asyncio.gather(*[self.embed_query(text) for text in texts]))

    async def aclose(self) -> None:
        await self._client.aclose()
