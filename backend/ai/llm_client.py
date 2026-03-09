from __future__ import annotations

from typing import Protocol

from backend.ai.ollama_llm_client import OllamaLLMClient
from backend.core.config import settings


class LLMClientProtocol(Protocol):
    async def generate(self, prompt: str) -> str: ...


class StubGroundedLLMClient:
    async def generate(self, prompt: str) -> str:
        lines = [
            line.strip()
            for line in prompt.splitlines()
            if line.strip().startswith("[SOURCE")
        ]
        references = ", ".join(line.split("]", 1)[0].strip("[") for line in lines[:3])
        if references:
            return f"Grounded draft answer based on {references}. Replace the stub client with Ollama for full generation."
        return "I do not have enough grounded sources to answer that confidently."


class LLMClientFactory:
    @staticmethod
    def create() -> LLMClientProtocol:
        if settings.effective_llm_provider == "ollama":
            return OllamaLLMClient(
                model=settings.OLLAMA_CHAT_MODEL, base_url=str(settings.OLLAMA_BASE_URL)
            )
        return StubGroundedLLMClient()
