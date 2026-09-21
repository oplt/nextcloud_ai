from __future__ import annotations

from typing import Any, Protocol

from ..core.config import settings
from .ollama_llm_client import (
    GenerationResult,
    LLMError,
    LLMHTTPError,
    LLMTimeoutError,
    LLMTransientError,
    LLMValidationError,
    OllamaLLMClient,
    consume_generation_usage,
    peek_generation_usage,
)


class LLMClientProtocol(Protocol):
    async def generate(self, prompt: str) -> str: ...

    @property
    def last_usage(self) -> dict[str, Any] | None: ...


class StubGroundedLLMClient:
    """Dev/test-only grounded stub. Not used as production fallback."""

    def __init__(self) -> None:
        self._usage: dict[str, Any] | None = None

    @property
    def last_usage(self) -> dict[str, Any] | None:
        return peek_generation_usage() or self._usage

    @last_usage.setter
    def last_usage(self, value: dict[str, Any] | None) -> None:
        self._usage = value
        from .ollama_llm_client import _generation_usage

        _generation_usage.set(value)

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
                f"Grounded draft answer based on {references}. "
                "Replace the stub client with Ollama for full generation."
            )
        else:
            response = (
                "I do not have enough grounded sources to answer that confidently."
            )
        input_tokens = self._estimate_tokens(prompt)
        output_tokens = self._estimate_tokens(response)
        usage = {
            "provider": "stub",
            "model": "stub",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "estimated_cost": 0.0,
            "cached": False,
        }
        self.last_usage = usage
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

    @property
    def last_usage(self) -> dict[str, Any] | None:
        return peek_generation_usage()

    @last_usage.setter
    def last_usage(self, value: dict[str, Any] | None) -> None:
        from .ollama_llm_client import _generation_usage

        _generation_usage.set(value)

    async def generate(self, prompt: str) -> str:
        try:
            return await self.primary.generate(prompt)
        except (LLMValidationError,) as exc:
            # Non-transient: never stub-mask validation failures.
            raise exc
        except Exception as exc:
            if self.fallback is None:
                raise
            # Only allow explicit non-production fallbacks.
            if settings.APP_ENV in {"staging", "production"}:
                raise
            response = await self.fallback.generate(prompt)
            usage = dict(peek_generation_usage() or {})
            usage["fallback_used"] = True
            usage["primary_error_type"] = type(exc).__name__
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
    def create(
        *,
        shared_cache: Any | None = None,
        reuse_process: bool = True,
    ) -> LLMClientProtocol:
        if reuse_process:
            try:
                from ..core.ai_resources import get_ai_resources

                bundle = get_ai_resources()
            except Exception:
                bundle = None
            else:
                if bundle is not None and bundle.llm_client is not None:
                    return bundle.llm_client
        else:
            bundle = None

        if settings.effective_llm_provider == "ollama":
            cache = shared_cache
            if cache is None and bundle is not None:
                cache = bundle.llm_cache
            primary: LLMClientProtocol = OllamaLLMClient(
                model=settings.OLLAMA_CHAT_MODEL,
                base_url=str(settings.OLLAMA_BASE_URL),
                timeout_seconds=settings.LLM_REQUEST_TIMEOUT_SECONDS,
                shared_cache=cache,
            )
            fallback: LLMClientProtocol | None = None
            allow_stub = (
                settings.LLM_FALLBACK_PROVIDER == "stub"
                and settings.APP_ENV not in {"staging", "production"}
            )
            if allow_stub:
                fallback = StubGroundedLLMClient()
            return ResilientLLMClient(primary=primary, fallback=fallback)
        return StubGroundedLLMClient()


__all__ = [
    "GenerationResult",
    "LLMClientFactory",
    "LLMClientProtocol",
    "LLMError",
    "LLMHTTPError",
    "LLMTimeoutError",
    "LLMTransientError",
    "LLMValidationError",
    "OllamaLLMClient",
    "ResilientLLMClient",
    "StubGroundedLLMClient",
    "consume_generation_usage",
    "peek_generation_usage",
]
