"""Offline RAG evaluation harness (structure + optional DB-backed runs)."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from ..core.config import settings
from ..core.security import AuthContext
from .offline_scorer import (
    answer_correctness,
    append_metrics_log,
    citation_correctness,
    load_gold_rows,
    precision_at_k,
    retrieval_hit_rate,
)
from ..services.retrieval_service import RetrievalService


async def _run_with_db(gold_path: Path) -> list[dict[str, object]]:
    from ..db.session import AsyncSessionLocal

    rows = load_gold_rows(gold_path)
    out: list[dict[str, object]] = []
    auth = AuthContext(
        user_id="00000000-0000-0000-0000-000000000001",
        auth_provider="local",
        username="eval",
        display_name="Eval",
        is_superuser=True,
        role_name="admin",
    )
    async with AsyncSessionLocal() as session:
        svc = RetrievalService(session)
        for row in rows:
            q = row["question"]
            expected = [str(x) for x in row.get("expected_document_ids") or []]
            exp_uuids = [UUID(x) for x in expected if x]
            res = await svc.retrieve(
                question=q,
                auth=auth,
                top_k=6,
                document_ids=exp_uuids if exp_uuids else None,
            )
            retrieved = [str(s.document_id) for s in res.sources]
            answer_text = "\n".join(source.content or source.snippet for source in res.sources)
            p3 = precision_at_k(expected, retrieved, 3)
            p6 = precision_at_k(expected, retrieved, 6)
            rec = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "id": row.get("id"),
                "retrieval_hit_rate": retrieval_hit_rate(expected, retrieved, 6),
                "precision@3": p3,
                "precision@6": p6,
                "answer_correctness": answer_correctness(
                    [str(x) for x in row.get("expected_answer_contains") or []],
                    answer_text,
                ),
                "citation_correctness": citation_correctness(expected, retrieved),
                "failure_rate": 0.0 if res.sources else 1.0,
                "retrieval_debug": res.retrieval_debug,
            }
            out.append(rec)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, default=Path(__file__).with_name("rag_gold.jsonl"))
    parser.add_argument("--with-db", action="store_true")
    args = parser.parse_args()
    if args.with_db:
        rows = asyncio.run(_run_with_db(args.gold))
    else:
        rows = [
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "id": r.get("id"),
                "retrieval_hit_rate": 0.0,
                "precision@3": 0.0,
                "precision@6": 0.0,
                "answer_correctness": 0.0,
                "citation_correctness": 0.0,
                "failure_rate": 1.0,
                "mode": "structure_only",
            }
            for r in load_gold_rows(args.gold)
        ]
    log_path = (
        Path(settings.RAG_EVAL_METRICS_LOG_PATH)
        if settings.RAG_EVAL_METRICS_LOG_PATH
        else None
    )
    for rec in rows:
        append_metrics_log(log_path, rec)
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
