"""Phase 3: live Ollama embedding compatibility smoke.

Requires a reachable Ollama with the configured embedding model.
Refuses silent truncation (truncate=false), checks dim/finite/norm, split+mean
pool for overlength inputs, and fingerprint mismatch rejection.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx

from backend.ai.embedding_contract import (
    EmbeddingValidationError,
    active_embedding_fingerprint,
    split_oversized_embedding_input,
    validate_embedding_vector,
)
from backend.ai.ollama_embedding_client import OllamaEmbeddingClient
from backend.core.config import settings


async def _ensure_model(base_url: str, model: str) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        tags = await client.get(f"{base_url.rstrip('/')}/api/tags")
        tags.raise_for_status()
        names = {
            str(item.get("name") or "") for item in (tags.json().get("models") or [])
        }
    if model in names:
        return

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            f"{base_url.rstrip('/')}/api/pull",
            json={"name": model, "stream": True},
        ) as response:
            response.raise_for_status()
            async for _line in response.aiter_lines():
                pass


async def _run(*, base_url: str, model: str, pull: bool) -> dict[str, object]:
    if pull:
        await _ensure_model(base_url, model)

    client = OllamaEmbeddingClient(
        model=model,
        base_url=base_url,
        expected_dim=settings.EMBEDDING_DIM,
        max_input_chars=settings.EMBEDDING_MAX_INPUT_CHARS,
    )
    try:
        # 1) Normal embed: count/dim/finite/norm
        vectors = await client.embed_documents(
            ["invoice EUR 42", "lunch is served at noon"]
        )
        if len(vectors) != 2:
            raise RuntimeError(f"expected 2 vectors, got {len(vectors)}")
        for vector in vectors:
            validate_embedding_vector(vector, expected_dim=settings.EMBEDDING_DIM)

        # 2) truncate=false path: oversized input must split+pool, not silently clip
        max_chars = min(512, int(settings.EMBEDDING_MAX_INPUT_CHARS))
        client.max_input_chars = max_chars
        overlength = ("token-α " * 400).strip()
        parts = split_oversized_embedding_input(overlength, max_chars=max_chars)
        if len(parts) < 2:
            raise RuntimeError("expected split_oversized to yield >=2 parts")
        pooled = await client.embed_documents([overlength])
        validate_embedding_vector(pooled[0], expected_dim=settings.EMBEDDING_DIM)

        # 3) Fingerprint identity is pinned to live model + schema dim
        fingerprint = active_embedding_fingerprint()
        if fingerprint.dimension != settings.EMBEDDING_DIM:
            raise RuntimeError("fingerprint dimension drifted from schema")
        if client.fingerprint.model != model:
            raise RuntimeError("client fingerprint model mismatch")

        # 4) Bad vector rejection still local (provider-independent contract)
        try:
            validate_embedding_vector(
                [0.0] * settings.EMBEDDING_DIM, expected_dim=settings.EMBEDDING_DIM
            )
            raise RuntimeError("zero vector should fail validation")
        except EmbeddingValidationError:
            pass

        return {
            "base_url": base_url,
            "model": model,
            "dimension": settings.EMBEDDING_DIM,
            "split_parts": len(parts),
            "fingerprint_digest": fingerprint.digest(),
            "sample_norm": sum(x * x for x in vectors[0]) ** 0.5,
        }
    finally:
        await client.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OLLAMA_BASE_URL", settings.OLLAMA_BASE_URL),
    )
    parser.add_argument(
        "--model",
        default=os.environ.get(
            "OLLAMA_EMBEDDING_MODEL", settings.OLLAMA_EMBEDDING_MODEL
        ),
    )
    parser.add_argument(
        "--pull",
        action="store_true",
        help="Pull the model if missing (can take several minutes).",
    )
    args = parser.parse_args(argv)
    try:
        # Probe reachability first for a clear skip/fail signal.
        httpx.get(
            f"{args.base_url.rstrip('/')}/api/tags", timeout=3.0
        ).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"ollama unreachable at {args.base_url}: {exc}",
                    "hint": "Start Ollama or run: make phase3-embed-smoke (starts disposable ollama)",
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    try:
        report = asyncio.run(
            _run(base_url=args.base_url, model=args.model, pull=args.pull)
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **report}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
