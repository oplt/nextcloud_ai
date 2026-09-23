from __future__ import annotations

import asyncio
import hashlib
import json
import random
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import httpx

from ..core.config import settings

# Per-asyncio-task usage — never share a mutable instance field across requests.
_generation_usage: ContextVar[dict[str, Any] | None] = ContextVar(
    "generation_usage", default=None
)


class LLMError(Exception):
    """Base typed LLM failure."""

    error_type = "llm_error"


class LLMTimeoutError(LLMError):
    error_type = "llm_timeout"


class LLMHTTPError(LLMError):
    error_type = "llm_http"

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMValidationError(LLMError):
    error_type = "llm_validation"


class LLMTransientError(LLMError):
    error_type = "llm_transient"


@dataclass(slots=True)
class GenerationResult:
    text: str
    usage: dict[str, Any]


def consume_generation_usage() -> dict[str, Any] | None:
    usage = _generation_usage.get()
    _generation_usage.set(None)
    return usage


def peek_generation_usage() -> dict[str, Any] | None:
    return _generation_usage.get()


class OllamaLLMClient:
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        max_connections: int = 4,
        timeout_seconds: float | None = None,
        shared_cache: Any | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_retries = settings.LLM_MAX_RETRIES
        self.retry_backoff_seconds = settings.LLM_RETRY_BACKOFF_SECONDS
        self._timeout = timeout_seconds or settings.LLM_REQUEST_TIMEOUT_SECONDS
        if shared_cache is not None:
            self._cache = shared_cache
        else:
            from ..core.async_cache import AsyncTTLCache

            self._cache = AsyncTTLCache(
                ttl_seconds=settings.LLM_CACHE_TTL_SECONDS,
                max_entries=settings.LLM_CACHE_MAX_ENTRIES,
            )
        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_connections,
            keepalive_expiry=30,
        )
        self._client = httpx.AsyncClient(timeout=self._timeout, limits=limits)

    @property
    def last_usage(self) -> dict[str, Any] | None:
        return peek_generation_usage()

    @last_usage.setter
    def last_usage(self, value: dict[str, Any] | None) -> None:
        _generation_usage.set(value)

    @staticmethod
    def _cache_key(model: str, prompt: str) -> str:
        serialized = json.dumps(
            {"model": model, "prompt": prompt},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text.split()))

    def _build_usage(
        self,
        *,
        prompt: str,
        response_text: str,
        response_payload: dict[str, Any],
        cached: bool,
    ) -> dict[str, Any]:
        prompt_tokens_raw = response_payload.get("prompt_eval_count")
        output_tokens_raw = response_payload.get("eval_count")
        prompt_tokens = (
            int(prompt_tokens_raw)
            if isinstance(prompt_tokens_raw, (int, float))
            else self._estimate_tokens(prompt)
        )
        output_tokens = (
            int(output_tokens_raw)
            if isinstance(output_tokens_raw, (int, float))
            else self._estimate_tokens(response_text)
        )
        input_cost = (prompt_tokens / 1000.0) * settings.LLM_COST_INPUT_PER_1K
        output_cost = (output_tokens / 1000.0) * settings.LLM_COST_OUTPUT_PER_1K
        return {
            "provider": "ollama",
            "model": self.model,
            "input_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "total_tokens": prompt_tokens + output_tokens,
            "estimated_cost": round(input_cost + output_cost, 8),
            "cached": cached,
        }

    @staticmethod
    def _is_transient(exc: BaseException) -> bool:
        if isinstance(
            exc, (LLMTimeoutError, LLMTransientError, httpx.TimeoutException)
        ):
            return True
        if isinstance(exc, httpx.TransportError):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in {408, 429, 500, 502, 503, 504}
        if isinstance(exc, LLMHTTPError):
            return exc.status_code in {408, 429, 500, 502, 503, 504}
        return False

    async def _generate_uncached(self, prompt: str) -> GenerationResult:
        deadline = asyncio.get_running_loop().time() + max(1.0, self._timeout * 2)
        attempts = max(0, self.max_retries) + 1
        last_error: Exception | None = None
        for attempt_index in range(attempts):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise LLMTimeoutError(
                    "Ollama generation deadline exceeded"
                ) from last_error
            try:
                response = await self._client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": self.model, "prompt": prompt, "stream": False},
                    timeout=min(self._timeout, remaining),
                )
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise LLMHTTPError(
                        f"Ollama HTTP {exc.response.status_code}",
                        status_code=exc.response.status_code,
                    ) from exc
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise LLMValidationError(
                        "Ollama response was not valid JSON"
                    ) from exc
                if not isinstance(payload, dict):
                    raise LLMValidationError("Ollama response was not a JSON object")
                response_text = str(payload.get("response") or "").strip()
                if not response_text:
                    raise LLMValidationError("LLM response was empty")
                usage = self._build_usage(
                    prompt=prompt,
                    response_text=response_text,
                    response_payload=payload,
                    cached=False,
                )
                return GenerationResult(text=response_text, usage=usage)
            except LLMValidationError:
                raise
            except LLMHTTPError as exc:
                last_error = exc
                if not self._is_transient(exc) or attempt_index >= attempts - 1:
                    raise
            except httpx.TimeoutException as exc:
                last_error = LLMTimeoutError(str(exc))
                if attempt_index >= attempts - 1:
                    raise last_error from exc
            except httpx.TransportError as exc:
                last_error = LLMTransientError(str(exc))
                if attempt_index >= attempts - 1:
                    raise last_error from exc
            except Exception as exc:
                last_error = LLMTransientError(str(exc))
                if not self._is_transient(exc) or attempt_index >= attempts - 1:
                    raise last_error from exc
            backoff = self.retry_backoff_seconds * (2**attempt_index)
            backoff *= 0.5 + random.random()
            await asyncio.sleep(min(backoff, max(0.0, remaining)))
        raise LLMTransientError("Ollama generation failed") from last_error

    async def generate_result(self, prompt: str) -> GenerationResult:
        cache_key = self._cache_key(self.model, prompt)
        cached = self._cache.get(cache_key)
        if isinstance(cached, dict) and isinstance(cached.get("text"), str):
            usage = dict(cached.get("usage") or {})
            usage["cached"] = True
            result = GenerationResult(text=str(cached["text"]), usage=usage)
            _generation_usage.set(usage)
            return result

        async def _fill() -> dict[str, Any]:
            result = await self._generate_uncached(prompt)
            return {"text": result.text, "usage": dict(result.usage)}

        payload = await self._cache.get_or_set(cache_key, _fill)
        usage = dict(payload.get("usage") or {})
        # First filler keeps cached=False; waiters after store still see False until
        # a later get() path. Mark waiters that didn't do the network call as cached
        # only when usage already has cached True from a prior get hit.
        text = str(payload["text"])
        result = GenerationResult(text=text, usage=usage)
        _generation_usage.set(usage)
        return result

    async def generate(self, prompt: str) -> str:
        result = await self.generate_result(prompt)
        return result.text

    async def aclose(self) -> None:
        await self._client.aclose()
