"""Phase 1A: load configured CrossEncoder and score a deterministic pair.

Refuse silent heuristic fallback. Exit 0 only when true model scores.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from types import SimpleNamespace
from uuid import uuid4

from backend.core.config import Settings
from backend.rag.rerank_runtime import (
    RerankDependencyError,
    ensure_reranker_ready,
    get_shared_reranker,
    reset_rerank_runtime_for_tests,
)
from backend.rag.stores import RetrievalCandidate


def _chunk(*, content: str, file_name: str, file_path: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        content=content,
        section_title=None,
        heading_path=None,
        metadata_json={},
        document=SimpleNamespace(
            file_name=file_name,
            file_path=file_path,
            metadata_json={},
        ),
    )


async def _run(*, force: bool) -> dict[str, object]:
    if force:
        reset_rerank_runtime_for_tests()
    cfg = Settings(
        RAG_TRUE_RERANK_ENABLED=True,
        RAG_TRUE_RERANK_PRELOAD=True,
        RAG_TRUE_RERANK_FALLBACK="fail",
        RAG_TRUE_RERANK_FAIL_STARTUP=False,
        APP_ENV="test",
    )
    status = await ensure_reranker_ready(settings_obj=cfg, force_reload=force)
    if not status.ready or status.using_fallback:
        raise RerankDependencyError(
            status.error or "true reranker not ready (fallback refused for smoke)"
        )
    reranker = get_shared_reranker()
    if reranker is None:
        raise RerankDependencyError("shared reranker missing after ready status")

    question = "What is the invoice total?"
    relevant = RetrievalCandidate(
        chunk=_chunk(  # type: ignore[arg-type]
            content="The invoice total is EUR 42.00 including VAT.",
            file_name="invoice.txt",
            file_path="/finance/invoice.txt",
        ),
        semantic_score=0.2,
        keyword_score=0.2,
        fused_score=0.2,
    )
    distractor = RetrievalCandidate(
        chunk=_chunk(  # type: ignore[arg-type]
            content="Lunch is served at noon in the cafeteria.",
            file_name="menu.txt",
            file_path="/hr/menu.txt",
        ),
        semantic_score=0.9,
        keyword_score=0.9,
        fused_score=0.9,
    )
    ranked = await reranker.rerank(question=question, candidates=[distractor, relevant])
    if len(ranked) != 2:
        raise RuntimeError("expected two ranked candidates")
    top = ranked[0]
    if top.chunk is not relevant.chunk:
        raise RuntimeError(
            "true reranker failed relevance order: "
            f"scores={[(c.chunk.document.file_name, c.rerank_score) for c in ranked]}"
        )
    if top.rerank_score is None:
        raise RuntimeError("missing rerank_score on top candidate")
    return {
        "status": status.to_dict(),
        "top_file": top.chunk.document.file_name,
        "scores": {
            candidate.chunk.document.file_name: candidate.rerank_score
            for candidate in ranked
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Clear process cache and reload the model.",
    )
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(_run(force=args.force))
    except Exception as exc:  # noqa: BLE001 - smoke surfaces any failure
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **report}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
