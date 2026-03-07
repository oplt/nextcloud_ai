from __future__ import annotations

import asyncio

import httpx

# Cap concurrent embed requests so we don't flood Ollama.
_DEFAULT_CONCURRENCY = 8


class OllamaEmbeddingClient:

    def __init__(
            self,
            model: str = "nomic-embed-text",
            base_url: str = "http://localhost:11434",
            max_concurrency: int = _DEFAULT_CONCURRENCY,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self._sem = asyncio.Semaphore(max_concurrency)

        # Explicit connection limits + keepalive avoid repeated TCP handshakes.
        limits = httpx.Limits(
            max_connections=max_concurrency,
            max_keepalive_connections=max_concurrency,
            keepalive_expiry=30,
        )
        self._client = httpx.AsyncClient(timeout=60, limits=limits)

    async def embed_query(self, text: str) -> list[float]:
        async with self._sem:
            resp = await self._client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
            )
        resp.raise_for_status()
        return resp.json()["embedding"]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # Fan-out all requests concurrently, throttled by the semaphore.
        return list(await asyncio.gather(*[self.embed_query(t) for t in texts]))

    async def aclose(self) -> None:
        await self._client.aclose()