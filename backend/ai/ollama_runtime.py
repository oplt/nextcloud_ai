from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

import httpx

from ..core.config import Settings, settings


@dataclass(slots=True, frozen=True)
class OllamaCapability:
    kind: Literal["chat", "embedding"]
    model: str


@dataclass(slots=True)
class OllamaRuntimeStatus:
    required: bool
    ready: bool
    providers: dict[str, str]
    base_url: str
    required_models: dict[str, str]
    available_models: list[str] = field(default_factory=list)
    missing_models: list[str] = field(default_factory=list)
    warmed_capabilities: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def status(self) -> str:
        if not self.required:
            return "disabled"
        return "ready" if self.ready else "not_ready"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "required": self.required,
            "providers": self.providers,
            "base_url": self.base_url,
            "required_models": self.required_models,
            "available_models": self.available_models,
            "missing_models": self.missing_models,
            "warmed_capabilities": self.warmed_capabilities,
            "error": self.error,
        }


class OllamaRuntimeService:
    def __init__(
        self,
        *,
        settings_obj: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings_obj or settings
        self.base_url = str(self.settings.OLLAMA_BASE_URL).rstrip("/")
        self.transport = transport

    def required_capabilities(self) -> list[OllamaCapability]:
        capabilities: list[OllamaCapability] = []
        if self.settings.effective_embedding_provider == "ollama":
            capabilities.append(
                OllamaCapability(
                    kind="embedding",
                    model=self.settings.OLLAMA_EMBEDDING_MODEL,
                )
            )
        if self.settings.effective_llm_provider == "ollama":
            capabilities.append(
                OllamaCapability(kind="chat", model=self.settings.OLLAMA_CHAT_MODEL)
            )
        return capabilities

    def _required_models(self) -> list[str]:
        models: list[str] = []
        seen: set[str] = set()
        for capability in self.required_capabilities():
            if capability.model in seen:
                continue
            seen.add(capability.model)
            models.append(capability.model)
        return models

    def _required_models_payload(self) -> dict[str, str]:
        payload: dict[str, str] = {}
        for capability in self.required_capabilities():
            payload[capability.kind] = capability.model
        return payload

    def _base_status(
        self,
        *,
        ready: bool,
        available_models: list[str] | None = None,
        missing_models: list[str] | (None) = None,
        warmed_capabilities: list[str] | None = None,
        error: str | None = None,
    ) -> OllamaRuntimeStatus:
        return OllamaRuntimeStatus(
            required=self.settings.ollama_required,
            ready=ready,
            providers={
                "embedding": self.settings.effective_embedding_provider,
                "llm": self.settings.effective_llm_provider,
            },
            base_url=self.base_url,
            required_models=self._required_models_payload(),
            available_models=available_models or [],
            missing_models=missing_models or [],
            warmed_capabilities=warmed_capabilities or [],
            error=error,
        )

    def _client(self, timeout_seconds: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout_seconds, transport=self.transport)

    @staticmethod
    def _extract_model_names(payload: dict[str, object]) -> list[str]:
        models = payload.get("models")
        if not isinstance(models, list):
            return []

        names: list[str] = []
        for model in models:
            if not isinstance(model, dict):
                continue
            candidate = model.get("name") or model.get("model")
            if isinstance(candidate, str):
                names.append(candidate)
        return names

    @staticmethod
    def _format_http_error(exc: httpx.HTTPError) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            detail = exc.response.text.strip()
            if detail:
                try:
                    payload = exc.response.json()
                except json.JSONDecodeError:
                    payload = None
                if isinstance(payload, dict):
                    detail = (
                        payload.get("error")
                        or payload.get("detail")
                        or payload.get("message")
                        or detail
                    )
            return f"Ollama request failed with status {exc.response.status_code}: {detail or 'unknown error'}"
        return f"Unable to reach Ollama at {exc.request.url}: {exc}"

    async def _list_models(self) -> list[str]:
        async with self._client(self.settings.OLLAMA_READINESS_TIMEOUT_SECONDS) as client:
            try:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                return self._extract_model_names(response.json())
            except httpx.HTTPError as exc:
                # Log the specific error for debugging
                print(f"Failed to list Ollama models: {self._format_http_error(exc)}")
                raise

    async def _pull_model(self, model: str) -> None:
        async with self._client(self.settings.OLLAMA_PULL_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{self.base_url}/api/pull",
                json={"model": model, "stream": False},
            )
            response.raise_for_status()

    async def _warm_embedding_model(self) -> None:
        async with self._client(self.settings.OLLAMA_WARMUP_TIMEOUT_SECONDS) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.settings.OLLAMA_EMBEDDING_MODEL, "input": "warmup"},
                )
                response.raise_for_status()
                return
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise

            # Backward compatibility with older Ollama versions.
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.settings.OLLAMA_EMBEDDING_MODEL, "prompt": "warmup"},
            )
            response.raise_for_status()

    async def _warm_chat_model(self) -> None:
        async with self._client(self.settings.OLLAMA_WARMUP_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.settings.OLLAMA_CHAT_MODEL,
                    "prompt": "Reply with READY.",
                    "stream": False,
                },
            )
            response.raise_for_status()

    async def check_readiness(self) -> OllamaRuntimeStatus:
        if not self.settings.ollama_required:
            return self._base_status(ready=True)

        try:
            available_models = await self._list_models()
            available_models = sorted(available_models)
        except httpx.HTTPError as exc:
            return self._base_status(ready=False, error=self._format_http_error(exc))

        required_models = self._required_models()
        missing_models = [model for model in required_models if model not in available_models]
        if missing_models:
            error = f"Missing required Ollama models: {', '.join(missing_models)}"
            return self._base_status(
                ready=False,
                available_models=available_models,
                missing_models=missing_models,
                error=error,
            )

        return self._base_status(ready=True, available_models=available_models)

    async def ensure_models_ready(self) -> OllamaRuntimeStatus:
        status = await self.check_readiness()
        if not status.required:
            return status
        if status.error and not status.missing_models:
            return status

        if status.missing_models:
            for model in status.missing_models:
                try:
                    await self._pull_model(model)
                except httpx.HTTPError as exc:
                    return self._base_status(
                        ready=False,
                        available_models=status.available_models,
                        missing_models=status.missing_models,
                        error=self._format_http_error(exc),
                    )

            status = await self.check_readiness()
            if not status.ready:
                return status

        warmed_capabilities: list[str] = []
        try:
            if self.settings.effective_embedding_provider == "ollama":
                await self._warm_embedding_model()
                warmed_capabilities.append("embedding")
            if self.settings.effective_llm_provider == "ollama":
                warmed_capabilities.append("chat")
        except httpx.HTTPError as exc:
            return self._base_status(
                ready=False,
                available_models=status.available_models,
                warmed_capabilities=warmed_capabilities,
                error=self._format_http_error(exc),
            )

        try:
            if self.settings.effective_llm_provider == "ollama":
                await self._warm_chat_model()
                warmed_capabilities.append("chat")
        except httpx.HTTPError as exc:
            return self._base_status(
                ready=False,
                available_models=status.available_models,
                warmed_capabilities=warmed_capabilities,
                error=self._format_http_error(exc),
            )

        status.warmed_capabilities = warmed_capabilities
        return status
