"""Pre-download / warm the configured true-rerank model (not on first request)."""

from __future__ import annotations

import argparse
import asyncio
import sys

from ..core.config import settings
from ..rag.rerank_runtime import RerankDependencyError, ensure_reranker_ready, reset_rerank_runtime_for_tests


async def _run(*, force: bool) -> int:
    if force:
        reset_rerank_runtime_for_tests()
    try:
        status = await ensure_reranker_ready(force_reload=force)
    except RerankDependencyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(status.to_dict())
    if status.enabled and not status.ready and not status.using_fallback:
        return 1
    if status.enabled and status.using_fallback and settings.RAG_TRUE_RERANK_FALLBACK == "fail":
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Clear process cache and reload the model.",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run(force=args.force))


if __name__ == "__main__":
    raise SystemExit(main())
