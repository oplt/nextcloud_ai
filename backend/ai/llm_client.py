from __future__ import annotations

from typing import Protocol


class LLMClientProtocol(Protocol):
    async def generate(self, prompt: str) -> str: ...


class SimpleGroundedLLMClient:
    """
    Development placeholder.

    Replace with Ollama or another local instruct model.
    """

    async def generate(self, prompt: str) -> str:
        # Minimal stub; swap out for real inference.
        return (
            "Grounded draft answer based on retrieved sources.\n\n"
            "Replace SimpleGroundedLLMClient with a real local model client."
        )