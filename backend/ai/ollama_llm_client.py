from __future__ import annotations

import httpx


class OllamaLLMClient:
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        max_connections: int = 4,
        timeout_seconds: float = 120,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_connections,
            keepalive_expiry=30,
        )
        self._client = httpx.AsyncClient(timeout=timeout_seconds, limits=limits)

    async def generate(self, prompt: str) -> str:
        response = await self._client.post(
            f"{self.base_url}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
        )
        response.raise_for_status()
        return response.json()["response"]

    async def aclose(self) -> None:
        await self._client.aclose()
