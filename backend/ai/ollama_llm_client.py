from __future__ import annotations

import httpx


class OllamaLLMClient:

    def __init__(
            self,
            model: str = "llama3:8b-instruct",
            base_url: str = "http://localhost:11434",
            max_connections: int = 4,
    ):
        self.model = model
        self.base_url = base_url

        # Explicit limits keep the connection pool warm between calls.
        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_connections,
            keepalive_expiry=30,
        )
        self._client = httpx.AsyncClient(timeout=120, limits=limits)

    async def generate(self, prompt: str) -> str:
        resp = await self._client.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
            },
        )
        resp.raise_for_status()
        return resp.json()["response"]

    async def aclose(self) -> None:
        await self._client.aclose()