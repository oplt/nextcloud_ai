from __future__ import annotations

from typing import Any
from typing import Protocol

from .ollama_llm_client import OllamaLLMClient
from ..core.config import settings


class LLMClientProtocol(Protocol):
    async def generate(self, prompt: str) -> str: ...
    last_usage: dict[str, Any] | None


class StubGroundedLLMClient:
    def __init__(self) -> None:
        self.last_usage: dict[str, Any] | None = None

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text.split()))

    async def generate(self, prompt: str) -> str:
        lines = [
            line.strip()
            for line in prompt.splitlines()
            if line.strip().startswith("[SOURCE")
        ]
        references = ", ".join(line.split("]", 1)[0].strip("[") for line in lines[:3])
        if references:
            response = (
                f"Grounded draft answer based on {references}. Replace the stub client with Ollama for full generation."
            )
        else:
            response = "I do not have enough grounded sources to answer that confidently."
        input_tokens = self._estimate_tokens(prompt)
        output_tokens = self._estimate_tokens(response)
        self.last_usage = {
            "provider": "stub",
            "model": "stub",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "estimated_cost": 0.0,
            "cached": False,
        }
        return response


class ResilientLLMClient:
    def __init__(
        self,
        *,
        primary: LLMClientProtocol,
        fallback: LLMClientProtocol | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.last_usage: dict[str, Any] | None = None

    async def generate(self, prompt: str) -> str:
        try:
            response = await self.primary.generate(prompt)
            self.last_usage = getattr(self.primary, "last_usage", None)
            return response
        except Exception:
            if self.fallback is None:
                raise
            response = await self.fallback.generate(prompt)
            usage = dict(getattr(self.fallback, "last_usage", {}) or {})
            usage["fallback_used"] = True
            usage["primary_provider"] = type(self.primary).__name__
            self.last_usage = usage
            return response

    async def aclose(self) -> None:
        primary_close = getattr(self.primary, "aclose", None)
        if callable(primary_close):
            await primary_close()
        fallback_close = getattr(self.fallback, "aclose", None)
        if callable(fallback_close):
            await fallback_close()


class LLMClientFactory:
    @staticmethod
    def create() -> LLMClientProtocol:
        if settings.effective_llm_provider == "ollama":
            primary: LLMClientProtocol = OllamaLLMClient(
                model=settings.OLLAMA_CHAT_MODEL,
                base_url=str(settings.OLLAMA_BASE_URL),
                timeout_seconds=settings.LLM_REQUEST_TIMEOUT_SECONDS,
            )
            fallback: LLMClientProtocol | None = None
            if settings.LLM_FALLBACK_PROVIDER == "stub":
                fallback = StubGroundedLLMClient()
            return ResilientLLMClient(primary=primary, fallback=fallback)
        return StubGroundedLLMClient()
