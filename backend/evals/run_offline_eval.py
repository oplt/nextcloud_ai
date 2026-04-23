"""Offline RAG evaluation harness (structure + optional DB-backed runs)."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from backend.core.config import settings
from backend.core.security import AuthContext
from backend.evals.offline_scorer import append_metrics_log, load_gold_rows, precision_at_k
from backend.services.retrieval_service import RetrievalService


async def _run_with_db(gold_path: Path) -> list[dict[str, object]]:
    from backend.db.session import AsyncSessionLocal

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
            p3 = precision_at_k(expected, retrieved, 3)
            p6 = precision_at_k(expected, retrieved, 6)
            rec = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "id": row.get("id"),
                "precision@3": p3,
                "precision@6": p6,
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
                "precision@3": 0.0,
                "precision@6": 0.0,
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
