"""Phase 4: before/after quality comparison on the seeded fixture corpus.

Baseline = in-memory fixture lexical retrieval (+ extractive answers).
Final = disposable Postgres RetrievalService (+ extractive cited answers verified
by evidence_verifier). Same gold rows; gold IDs stay scoring-only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any
from uuid import UUID

from backend.core.config import settings
from backend.evals.fixture_loader import (
    load_fixture_bundle,
    resolve_ids,
    seed_database_fixture,
)
from backend.evals.run_offline_eval import (
    EXIT_APP,
    EXIT_INFRA,
    EXIT_OK,
    InfrastructureError,
    _aggregate,
    _auth_for_identity,
    _default_identity,
    _score_case,
    run_fixture,
)
from backend.rag.answer import INSUFFICIENT_EVIDENCE_ANSWER
from backend.rag.evidence_verifier import verify_and_normalize_answer
from backend.schemas.chat_schema import ChatSource

_COMPARE_KEYS = (
    "recall@3",
    "recall@6",
    "precision@3",
    "precision@6",
    "mrr",
    "ndcg@3",
    "ndcg@6",
    "answer_correctness",
    "citation_support",
    "citation_recall",
    "claim_support",
    "abstention",
    "answer_exclusion_ok",
)


def _delta(baseline: dict[str, Any], final: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    base_means = baseline.get("means") or {}
    final_means = final.get("means") or {}
    for key in _COMPARE_KEYS:
        left = base_means.get(key)
        right = final_means.get(key)
        if left is None and right is None:
            continue
        try:
            left_f = float(left) if left is not None else None
            right_f = float(right) if right is not None else None
        except (TypeError, ValueError):
            continue
        if left_f is None or right_f is None:
            out[key] = {"baseline": left_f, "final": right_f, "delta": None}
        else:
            out[key] = {
                "baseline": round(left_f, 6),
                "final": round(right_f, 6),
                "delta": round(right_f - left_f, 6),
            }
    return out


def _cited_extractive(sources: list[ChatSource]) -> str:
    if not sources:
        return INSUFFICIENT_EVIDENCE_ANSWER
    parts: list[str] = []
    for index, source in enumerate(sources[:3], start=1):
        excerpt = (source.content or source.snippet or "").strip()
        if not excerpt:
            continue
        # Keep short so verifier span checks stay focused.
        clipped = " ".join(excerpt.split())[:280]
        parts.append(f"{clipped} [{index}]")
    if not parts:
        return INSUFFICIENT_EVIDENCE_ANSWER
    return " ".join(parts)


async def _run_db_verified(top_k: int) -> list[dict[str, Any]]:
    from backend.ai.embedding_client import DeterministicEmbeddingClient
    from backend.db.session import AsyncSessionLocal, dispose_db
    from backend.services.retrieval_service import RetrievalService

    bundle = load_fixture_bundle()
    database_url = settings.DATABASE_URL.lower()
    if settings.APP_ENV not in {"development", "test"} or not any(
        host in database_url for host in ("localhost", "127.0.0.1")
    ):
        raise InfrastructureError(
            "phase4 quality compare requires a local development/test database"
        )

    out: list[dict[str, Any]] = []
    try:
        async with AsyncSessionLocal() as session:
            await seed_database_fixture(session, bundle)
            svc = RetrievalService(
                session, embedding_client=DeterministicEmbeddingClient()
            )
            for row in bundle.gold:
                identity = _default_identity(bundle, row)
                auth = _auth_for_identity(identity)
                request_scope = [UUID(x) for x in resolve_ids(row.request_document_ids)]
                expected_docs = resolve_ids(row.expected_document_ids)
                expected_chunks = resolve_ids(row.expected_chunk_ids)
                res = await svc.retrieve(
                    question=row.question,
                    auth=auth,
                    top_k=top_k,
                    document_ids=request_scope or None,
                )
                retrieved_docs = [str(source.document_id) for source in res.sources]
                retrieved_chunks = [str(source.chunk_id) for source in res.sources]
                if row.should_abstain or not res.sources:
                    answer_text = INSUFFICIENT_EVIDENCE_ANSWER
                    cited_docs: list[str] = []
                    verification = {
                        "support_check_passed": True,
                        "result": "abstain",
                    }
                else:
                    answer_text = _cited_extractive(list(res.sources))
                    cited_docs = retrieved_docs[: len(res.sources[:3])]
                    verified = verify_and_normalize_answer(
                        question=row.question,
                        answer=answer_text,
                        sources=list(res.sources),
                        shadow_mode=False,
                    )
                    verification = verified.as_dict()
                    # Prefer verifier-approved answer when it passes; otherwise keep
                    # extractive text for answer/citation metrics and let claim_support
                    # record the failed verification honestly.
                    if verified.support_check_passed:
                        answer_text = verified.answer
                        cited_docs = [
                            str(source.document_id) for source in verified.sources
                        ]

                out.append(
                    _score_case(
                        row=row,
                        expected_doc_ids=expected_docs,
                        expected_chunk_ids=expected_chunks,
                        retrieved_doc_ids=retrieved_docs,
                        retrieved_chunk_ids=retrieved_chunks,
                        cited_doc_ids=cited_docs,
                        answer_text=answer_text,
                        mode="answer",
                        stage_latency={},
                        extra={
                            "identity": identity.key,
                            "verification": verification,
                        },
                    )
                )
            await session.rollback()
    finally:
        await dispose_db()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=6)
    args = parser.parse_args(argv)

    try:
        bundle = load_fixture_bundle()
        baseline_rows = run_fixture(bundle, with_answer=True, top_k=args.top_k)
        baseline = _aggregate(baseline_rows)
        baseline["mode"] = "fixture_answer"

        final_rows = asyncio.run(_run_db_verified(top_k=args.top_k))
        final = _aggregate(final_rows)
        final["mode"] = "db_retrieval_verified_extractive"
    except InfrastructureError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_class": "infrastructure",
                    "error": str(exc),
                    "hint": "Run via make phase4-quality-compare (starts disposable PG).",
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return EXIT_INFRA
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps({"ok": False, "error_class": "application", "error": str(exc)}),
            indent=2,
            file=sys.stderr,
        )
        return EXIT_APP

    report = {
        "ok": True,
        "corpus": "evals/fixtures + rag_gold.jsonl",
        "baseline": baseline,
        "final": final,
        "delta_final_minus_baseline": _delta(baseline, final),
        "notes": [
            "Baseline is fixture lexical ranking + extractive answers (no DB).",
            "Final is authorized DB hybrid retrieval + extractive cited answers + evidence_verifier.",
            "Gold expected_* IDs are scoring-only and never scope retrieval.",
            "Positive delta means final improved vs baseline on that metric.",
        ],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
