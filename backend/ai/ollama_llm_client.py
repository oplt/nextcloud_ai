from __future__ import annotations

import asyncio
from collections import OrderedDict
import hashlib
import httpx
import json
from typing import Any

from ..core.config import settings


class _TTLCache:
    def __init__(self, *, ttl_seconds: int, max_entries: int) -> None:
        self.ttl_seconds = max(0, ttl_seconds)
        self.max_entries = max(0, max_entries)
        self._store: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def get(self, key: str) -> str | None:
        if self.ttl_seconds <= 0 or self.max_entries <= 0:
            return None
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= asyncio.get_running_loop().time():
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: str) -> None:
        if self.ttl_seconds <= 0 or self.max_entries <= 0:
            return
        now = asyncio.get_running_loop().time()
        self._store[key] = (now + self.ttl_seconds, value)
        self._store.move_to_end(key)
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)


class OllamaLLMClient:
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        max_connections: int = 4,
        timeout_seconds: float | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_retries = settings.LLM_MAX_RETRIES
        self.retry_backoff_seconds = settings.LLM_RETRY_BACKOFF_SECONDS
        self.last_usage: dict[str, Any] | None = None
        self._cache = _TTLCache(
            ttl_seconds=settings.LLM_CACHE_TTL_SECONDS,
            max_entries=settings.LLM_CACHE_MAX_ENTRIES,
        )
        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_connections,
            keepalive_expiry=30,
        )
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds or settings.LLM_REQUEST_TIMEOUT_SECONDS,
            limits=limits,
        )

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
        self, *, prompt: str, response_text: str, response_payload: dict[str, Any], cached: bool
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
        total_cost = round(input_cost + output_cost, 8)
        return {
            "provider": "ollama",
            "model": self.model,
            "input_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "total_tokens": prompt_tokens + output_tokens,
            "estimated_cost": total_cost,
            "cached": cached,
        }

    async def generate(self, prompt: str) -> str:
        cache_key = self._cache_key(self.model, prompt)
        cached = self._cache.get(cache_key)
        if cached is not None:
            self.last_usage = self._build_usage(
                prompt=prompt,
                response_text=cached,
                response_payload={},
                cached=True,
            )
            return cached

        attempts = max(0, self.max_retries) + 1
        last_error: Exception | None = None
        for attempt_index in range(attempts):
            try:
                response = await self._client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": self.model, "prompt": prompt, "stream": False},
                )
                response.raise_for_status()
                payload = response.json()
                response_text = str(payload.get("response") or "").strip()
                if not response_text:
                    raise ValueError("LLM response was empty")
                self.last_usage = self._build_usage(
                    prompt=prompt,
                    response_text=response_text,
                    response_payload=payload if isinstance(payload, dict) else {},
                    cached=False,
                )
                self._cache.set(cache_key, response_text)
                return response_text
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt_index >= attempts - 1:
                    break
                backoff = self.retry_backoff_seconds * (2**attempt_index)
                if backoff > 0:
                    await asyncio.sleep(backoff)
        raise RuntimeError("Ollama generation failed") from last_error

    async def aclose(self) -> None:
        await self._client.aclose()
