"""Offline RAG evaluation harness.

Modes
-----
* ``structure`` — validate gold/fixtures; no retrieval.
* ``fixture`` — in-memory lexical retrieval over the seeded corpus (no DB).
* ``retrieval`` — DB-backed ``RetrievalService`` (requires Postgres/pgvector).
* ``answer`` — retrieval + grounded answer generation/verification.

Gold ``expected_*`` IDs are scoring-only. Only ``request_document_ids`` may
restrict retrieval scope. Exit code ``2`` = infrastructure missing/unreachable;
``1`` = application/evaluation failure; ``0`` = success.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from ..core.config import settings
from ..core.security import AuthContext
from .fixture_loader import (
    EvalFixtureBundle,
    FixtureDocument,
    FixtureIdentity,
    documents_visible_to,
    load_fixture_bundle,
    resolve_ids,
    seed_database_fixture,
)
from .offline_scorer import (
    OfflineEvalRow,
    abstention_score,
    answer_correctness,
    answer_exclusion_ok,
    append_metrics_log,
    citation_recall,
    citation_support,
    mean_metrics,
    score_retrieval,
)

EXIT_OK = 0
EXIT_APP = 1
EXIT_INFRA = 2

_TOKEN_RE = re.compile(r"[a-z0-9\-_./]+", re.IGNORECASE)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "to",
        "of",
        "in",
        "on",
        "for",
        "and",
        "or",
        "what",
        "which",
        "who",
        "how",
        "many",
        "much",
        "does",
        "do",
        "did",
        "with",
        "from",
        "at",
        "by",
        "into",
        "that",
        "this",
        "it",
        "as",
        "per",
    }
)


def _tokenize(text: str) -> set[str]:
    tokens = {
        token.lower() for token in _TOKEN_RE.findall(text or "") if len(token) > 1
    }
    return {token for token in tokens if token not in _STOPWORDS}


class InfrastructureError(RuntimeError):
    """Postgres/Redis/Ollama/network missing — not an application regression."""


class _DatabaseMetrics:
    def __init__(self) -> None:
        self.statements = 0
        self.rows = 0
        self.connections = 0
        self._target: object | None = None

    def attach(self, session: object) -> None:
        from sqlalchemy import event

        bind = getattr(session, "bind", None)
        target = getattr(bind, "sync_engine", None)
        if target is None:
            return
        self._target = target
        event.listen(target, "before_cursor_execute", self._before_cursor_execute)
        event.listen(target, "after_cursor_execute", self._after_cursor_execute)
        event.listen(target, "engine_connect", self._engine_connect)

    def detach(self) -> None:
        if self._target is None:
            return
        from sqlalchemy import event

        event.remove(self._target, "before_cursor_execute", self._before_cursor_execute)
        event.remove(self._target, "after_cursor_execute", self._after_cursor_execute)
        event.remove(self._target, "engine_connect", self._engine_connect)
        self._target = None

    def _before_cursor_execute(self, *_args: object) -> None:
        self.statements += 1

    def _after_cursor_execute(
        self,
        _connection: object,
        _cursor_connection: object,
        _statement: object,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        cursor = _cursor_connection
        rowcount = getattr(cursor, "rowcount", -1)
        if isinstance(rowcount, int) and rowcount > 0:
            self.rows += rowcount

    def _engine_connect(self, *_args: object) -> None:
        self.connections += 1

    def as_dict(self) -> dict[str, int]:
        return {
            "sql_statements": self.statements,
            "reported_rows": self.rows,
            "connections": self.connections,
        }


def _auth_for_identity(identity: FixtureIdentity) -> AuthContext:
    return AuthContext(
        user_id=str(identity.user_id),
        auth_provider="local",
        username=identity.username,
        display_name=identity.display_name,
        is_superuser=identity.is_superuser,
        role_name=identity.role_name,
    )


def _default_identity(
    bundle: EvalFixtureBundle, row: OfflineEvalRow
) -> FixtureIdentity:
    key = row.request_auth or "admin"
    if key not in bundle.identities_by_key:
        raise ValueError(f"Unknown request_auth identity '{key}' for case {row.id}")
    return bundle.identities_by_key[key]


def _lexical_rank_documents(
    *,
    question: str,
    documents: list[FixtureDocument],
    request_document_ids: list[str] | None,
    top_k: int,
) -> tuple[list[str], list[str], list[FixtureDocument]]:
    """Simple term-overlap ranking over fixture docs (fast baseline, no DB)."""
    scope = set(request_document_ids or [])
    q_tokens = _tokenize(question)
    scored: list[tuple[float, FixtureDocument]] = []
    for doc in documents:
        doc_id = str(doc.document_id)
        if scope and doc_id not in scope:
            continue
        corpus_tokens = _tokenize(doc.text + " " + doc.title + " " + doc.file_path)
        overlap = len(q_tokens & corpus_tokens)
        if overlap <= 0:
            continue
        # Prefer denser overlap and exact path/id tokens.
        bonus = (
            2.0
            if any(
                tok.upper().startswith("INV-") and tok.upper() in doc.text.upper()
                for tok in q_tokens
            )
            else 0.0
        )
        scored.append((float(overlap) + bonus, doc))
    scored.sort(key=lambda item: (-item[0], item[1].key))
    chosen = [doc for _, doc in scored[:top_k]]
    doc_ids = [str(doc.document_id) for doc in chosen]
    chunk_ids: list[str] = []
    for doc in chosen:
        best_chunk = None
        best_score = -1
        for chunk in doc.chunks:
            overlap = len(q_tokens & _tokenize(chunk.text))
            if overlap > best_score:
                best_score = overlap
                best_chunk = chunk
        if best_chunk is not None:
            chunk_ids.append(str(best_chunk.chunk_id))
    return doc_ids, chunk_ids, chosen


def _score_case(
    *,
    row: OfflineEvalRow,
    expected_doc_ids: list[str],
    expected_chunk_ids: list[str],
    retrieved_doc_ids: list[str],
    retrieved_chunk_ids: list[str],
    cited_doc_ids: list[str],
    answer_text: str | None,
    mode: str,
    stage_latency: dict[str, float],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    expected_cite = (
        resolve_ids(row.expected_cited_document_ids)
        if row.expected_cited_document_ids
        else expected_doc_ids
    )
    doc_metrics = (
        score_retrieval(
            expected_ids=expected_doc_ids,
            retrieved_ids=retrieved_doc_ids,
            unit="document",
        )
        if expected_doc_ids
        else {}
    )
    chunk_metrics = (
        score_retrieval(
            expected_ids=expected_chunk_ids,
            retrieved_ids=retrieved_chunk_ids,
            unit="chunk",
        )
        if expected_chunk_ids
        else {}
    )

    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "id": row.id,
        "mode": mode,
        "language": row.language,
        "unit": "document",
        "question": row.question,
        "expected_document_ids": expected_doc_ids,
        "retrieved_document_ids": retrieved_doc_ids,
        "retrieved_chunk_ids": retrieved_chunk_ids,
        "request_document_ids": resolve_ids(row.request_document_ids),
        "request_auth": row.request_auth,
        "tags": row.tags,
        **{f"document_{key}": value for key, value in doc_metrics.items()},
        # Backward-compatible short names (document unit).
        "retrieval_hit_rate": doc_metrics.get("hit_rate@6"),
        "precision@3": doc_metrics.get("precision@3"),
        "precision@6": doc_metrics.get("precision@6"),
        "recall@3": doc_metrics.get("recall@3"),
        "recall@6": doc_metrics.get("recall@6"),
        "mrr": doc_metrics.get("mrr"),
        "ndcg@3": doc_metrics.get("ndcg@3"),
        "ndcg@6": doc_metrics.get("ndcg@6"),
        "precision_over_returned@6": doc_metrics.get("precision_over_returned@6"),
        "failure_rate": 0.0 if retrieved_doc_ids or row.should_abstain else 1.0,
        "stage_latency_seconds": stage_latency,
    }
    for key, value in chunk_metrics.items():
        record[f"chunk_{key}"] = value

    if mode in {"answer", "fixture_answer"} and answer_text is not None:
        record["answer"] = answer_text
        record["answer_correctness"] = answer_correctness(
            row.expected_answer_contains, answer_text
        )
        record["answer_exclusion_ok"] = answer_exclusion_ok(
            row.expected_answer_excludes, answer_text
        )
        if expected_cite:
            record["citation_support"] = citation_support(expected_cite, cited_doc_ids)
            record["citation_correctness"] = record["citation_support"]
            record["citation_recall"] = citation_recall(expected_cite, cited_doc_ids)
        else:
            record["citation_support"] = None
            record["citation_correctness"] = None
            record["citation_recall"] = None
        record["abstention"] = abstention_score(
            should_abstain=row.should_abstain,
            answer=answer_text,
            retrieved_count=len(retrieved_doc_ids),
            cited_count=len(cited_doc_ids),
        )
    elif mode in {"retrieval", "fixture"}:
        record["answer_correctness"] = None
        record["citation_correctness"] = None
        record["citation_support"] = None
        record["citation_recall"] = None
        record["answer_exclusion_ok"] = None
        record["abstention"] = None
        record["answer_eval"] = "skipped_retrieval_only"
    else:
        record["answer_correctness"] = 0.0
        record["citation_correctness"] = 0.0
        record["abstention"] = 0.0

    if extra:
        record.update(extra)
        verification = extra.get("verification")
        if mode == "answer" and isinstance(verification, dict):
            record["claim_support"] = (
                1.0 if verification.get("support_check_passed") is True else 0.0
            )
    return record


def _extractive_answer(row: OfflineEvalRow, docs: list[FixtureDocument]) -> str:
    if row.should_abstain or not docs:
        return (
            "I could not verify this from the retrieved indexed sources. "
            "The available evidence is insufficient to answer without guessing."
        )
    excerpts = []
    for doc in docs[:3]:
        excerpts.append(doc.chunks[0].text if doc.chunks else doc.text)
    joined = "\n".join(excerpts)
    return f"Based on the sources: {joined}"


def run_structure(bundle: EvalFixtureBundle) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in bundle.gold:
        rows.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "id": row.id,
                "mode": "structure",
                "ok": bool(row.question),
                "expected_document_ids": resolve_ids(row.expected_document_ids),
                "request_document_ids": resolve_ids(row.request_document_ids),
                "fixture_docs": len(bundle.documents),
                "answer_eval": "skipped_structure_only",
                "retrieval_hit_rate": None,
                "precision@3": None,
                "precision@6": None,
                "answer_correctness": None,
                "citation_correctness": None,
                "failure_rate": 0.0,
            }
        )
    return rows


def run_fixture(
    bundle: EvalFixtureBundle, *, with_answer: bool = False, top_k: int = 6
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    mode = "fixture_answer" if with_answer else "fixture"
    for row in bundle.gold:
        identity = _default_identity(bundle, row)
        visible = documents_visible_to(bundle, identity.key)
        request_scope = resolve_ids(row.request_document_ids)
        expected_docs = resolve_ids(row.expected_document_ids)
        expected_chunks = resolve_ids(row.expected_chunk_ids)
        stage: dict[str, float] = {}
        started = time.perf_counter()
        retrieved_docs, retrieved_chunks, chosen = _lexical_rank_documents(
            question=row.question,
            documents=visible,
            request_document_ids=request_scope or None,
            top_k=top_k,
        )
        stage["retrieval"] = time.perf_counter() - started
        answer_text: str | None = None
        cited = list(retrieved_docs)
        if with_answer:
            started_ans = time.perf_counter()
            answer_text = _extractive_answer(row, chosen)
            stage["answer"] = time.perf_counter() - started_ans
        out.append(
            _score_case(
                row=row,
                expected_doc_ids=expected_docs,
                expected_chunk_ids=expected_chunks,
                retrieved_doc_ids=retrieved_docs,
                retrieved_chunk_ids=retrieved_chunks,
                cited_doc_ids=cited,
                answer_text=answer_text,
                mode=mode,
                stage_latency=stage,
                extra={"identity": identity.key},
            )
        )
    return out


async def _run_db_cases(
    bundle: EvalFixtureBundle,
    *,
    with_answer: bool,
    top_k: int,
    seed_database: bool = False,
) -> list[dict[str, Any]]:
    try:
        from ..db.session import AsyncSessionLocal
    except Exception as exc:  # pragma: no cover - import env issues
        raise InfrastructureError(f"Database session import failed: {exc}") from exc

    from ..ai.llm_client import LLMClientFactory
    from ..ai.prompt_builder import build_grounded_prompt
    from ..core.config import settings
    from ..rag.answer import INSUFFICIENT_EVIDENCE_ANSWER
    from ..rag.context_packer import pack_evidence_for_prompt
    from ..rag.evidence_verifier import verify_and_normalize_answer
    from ..services.retrieval_service import RetrievalService

    out: list[dict[str, Any]] = []
    mode = "answer" if with_answer else "retrieval"
    llm = LLMClientFactory.create() if with_answer else None

    try:
        try:
            session_cm = AsyncSessionLocal()
        except Exception as exc:
            raise InfrastructureError(f"Database session unavailable: {exc}") from exc

        async with session_cm as session:
            database_metrics = _DatabaseMetrics()
            database_metrics.attach(session)
            if seed_database:
                database_url = settings.DATABASE_URL.lower()
                if settings.APP_ENV not in {"development", "test"} or not any(
                    host in database_url for host in ("localhost", "127.0.0.1")
                ):
                    raise InfrastructureError(
                        "--seed-db is restricted to a local development/test database"
                    )
                await seed_database_fixture(session, bundle)
            eval_embedding_client = None
            if (
                seed_database
                and settings.effective_embedding_provider == "deterministic"
            ):
                from ..ai.embedding_client import DeterministicEmbeddingClient

                eval_embedding_client = DeterministicEmbeddingClient()
            if eval_embedding_client is None:
                svc = RetrievalService(session)
            else:
                svc = RetrievalService(
                    session,
                    embedding_client=eval_embedding_client,
                )
            for row in bundle.gold:
                identity = _default_identity(bundle, row)
                auth = _auth_for_identity(identity)
                # Gold expected IDs stay out of retrieval kwargs.
                request_scope = [UUID(x) for x in resolve_ids(row.request_document_ids)]
                expected_docs = resolve_ids(row.expected_document_ids)
                expected_chunks = resolve_ids(row.expected_chunk_ids)
                stage: dict[str, float] = {}
                started = time.perf_counter()
                try:
                    res = await svc.retrieve(
                        question=row.question,
                        auth=auth,
                        top_k=top_k,
                        document_ids=request_scope or None,
                    )
                except Exception as exc:
                    message = str(exc).lower()
                    infra_markers = (
                        "connect",
                        "connection",
                        "timeout",
                        "could not translate host",
                        "redis",
                        "postgres",
                        "operationalerror",
                        "connectionrefused",
                    )
                    if any(marker in message for marker in infra_markers):
                        raise InfrastructureError(
                            f"Retrieval infrastructure failure on {row.id}: {exc}"
                        ) from exc
                    raise
                stage["retrieval"] = time.perf_counter() - started

                retrieved_docs = [str(source.document_id) for source in res.sources]
                retrieved_chunks = [str(source.chunk_id) for source in res.sources]
                # Dedup document ranking for document-unit metrics is handled in scorer.
                answer_text: str | None = None
                cited_docs: list[str] = []
                answer_extra: dict[str, Any] = {}
                if with_answer and llm is not None:
                    started_ans = time.perf_counter()
                    if not res.sources:
                        raw_answer = INSUFFICIENT_EVIDENCE_ANSWER
                        answer_extra["answer_mode"] = "deterministic_abstention"
                    else:
                        overhead_prompt = build_grounded_prompt(row.question, [])
                        packed = pack_evidence_for_prompt(
                            list(res.sources),
                            question=row.question,
                            prompt_overhead_text=overhead_prompt,
                            context_tokens=settings.RAG_PROMPT_CONTEXT_TOKENS,
                            output_reserve_tokens=settings.RAG_PROMPT_OUTPUT_RESERVE_TOKENS,
                            margin_tokens=settings.RAG_PROMPT_MARGIN_TOKENS,
                            per_source_cap_tokens=settings.RAG_PROMPT_PER_SOURCE_CAP_TOKENS,
                        )
                        prompt = build_grounded_prompt(row.question, packed.sources)
                        raw_answer = await llm.generate(prompt)
                        answer_extra["answer_mode"] = "generated_verified"
                    stage["answer"] = time.perf_counter() - started_ans

                    started_verify = time.perf_counter()
                    verified = verify_and_normalize_answer(
                        question=row.question,
                        answer=raw_answer,
                        sources=packed.sources if res.sources else [],
                        shadow_mode=False,
                    )
                    stage["verification"] = time.perf_counter() - started_verify
                    answer_text = verified.answer
                    cited_docs = [
                        str(source.document_id) for source in verified.sources
                    ]
                    answer_extra["verification"] = verified.as_dict()

                out.append(
                    _score_case(
                        row=row,
                        expected_doc_ids=expected_docs,
                        expected_chunk_ids=expected_chunks,
                        retrieved_doc_ids=retrieved_docs,
                        retrieved_chunk_ids=retrieved_chunks,
                        cited_doc_ids=cited_docs,
                        answer_text=answer_text,
                        mode=mode,
                        stage_latency=stage,
                        extra={
                            "identity": identity.key,
                            "retrieval_debug": res.retrieval_debug,
                            **answer_extra,
                        },
                    )
                )
            if seed_database:
                await session.rollback()
            database_metrics.detach()
            if out:
                out[-1]["database_metrics"] = database_metrics.as_dict()
    finally:
        close = getattr(llm, "aclose", None)
        if callable(close):
            await close()

    return out


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    keys = [
        "recall@3",
        "recall@6",
        "precision@3",
        "precision@6",
        "precision_over_returned@6",
        "mrr",
        "ndcg@3",
        "ndcg@6",
        "retrieval_hit_rate",
        "answer_correctness",
        "citation_support",
        "citation_correctness",
        "citation_recall",
        "claim_support",
        "answer_exclusion_ok",
        "abstention",
        "failure_rate",
    ]
    means = mean_metrics(records, keys)
    stage_names = {
        stage
        for rec in records
        if isinstance(rec.get("stage_latency_seconds"), dict)
        for stage in rec["stage_latency_seconds"]
    }
    stage_samples = {
        stage: sorted(
            float(rec["stage_latency_seconds"][stage])
            for rec in records
            if isinstance(rec.get("stage_latency_seconds"), dict)
            and stage in rec["stage_latency_seconds"]
        )
        for stage in sorted(stage_names)
    }
    stage_means = {
        stage: sum(samples) / len(samples) for stage, samples in stage_samples.items()
    }
    stage_percentiles = {
        stage: {
            percentile: _percentile(samples, quantile)
            for percentile, quantile in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99))
        }
        for stage, samples in stage_samples.items()
    }
    summary = {
        "case_count": len(records),
        "means": means,
        "stage_latency_mean_seconds": stage_means,
        "stage_latency_percentiles_seconds": stage_percentiles,
        "retrieval_latency_mean_seconds": stage_means.get("retrieval"),
    }
    database_metrics = next(
        (
            rec["database_metrics"]
            for rec in reversed(records)
            if isinstance(rec.get("database_metrics"), dict)
        ),
        None,
    )
    if database_metrics is not None:
        summary["database_metrics"] = database_metrics
    return summary


def _percentile(samples: list[float], quantile: float) -> float:
    """Linearly interpolated percentile for deterministic eval summaries."""
    if not samples:
        return 0.0
    if len(samples) == 1:
        return samples[0]
    position = (len(samples) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(samples) - 1)
    fraction = position - lower
    return samples[lower] + (samples[upper] - samples[lower]) * fraction


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gold",
        type=Path,
        default=Path(__file__).with_name("rag_gold.jsonl"),
        help="Gold JSONL path (fixture keys or UUIDs).",
    )
    parser.add_argument(
        "--mode",
        choices=("structure", "fixture", "retrieval", "answer"),
        default="fixture",
        help="Evaluation mode. retrieval/answer need disposable Postgres.",
    )
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument(
        "--seed-db",
        action="store_true",
        help=(
            "Seed fixtures inside a rollback-only transaction. Restricted to "
            "local development/test databases."
        ),
    )
    parser.add_argument(
        "--with-db",
        action="store_true",
        help="Deprecated alias: sets --mode retrieval when mode is fixture.",
    )
    parser.add_argument(
        "--with-answer",
        action="store_true",
        help="Deprecated alias: sets --mode answer.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print aggregate summary instead of per-case rows.",
    )
    args = parser.parse_args(argv)

    mode = args.mode
    fixture_with_answer = False
    if args.with_answer and mode in {"retrieval", "answer"}:
        mode = "answer"
    elif args.with_answer and mode == "fixture":
        fixture_with_answer = True
    elif args.with_db and mode == "fixture":
        mode = "retrieval"

    try:
        bundle = load_fixture_bundle(gold_path=args.gold)
    except OSError as exc:
        print(
            json.dumps({"error_class": "infrastructure", "error": str(exc)}),
            file=sys.stderr,
        )
        return EXIT_INFRA
    except Exception as exc:
        print(
            json.dumps({"error_class": "application", "error": str(exc)}),
            file=sys.stderr,
        )
        return EXIT_APP

    try:
        if mode == "structure":
            records = run_structure(bundle)
        elif mode == "fixture":
            records = run_fixture(
                bundle, with_answer=fixture_with_answer, top_k=args.top_k
            )
            if fixture_with_answer:
                mode = "fixture_answer"
        elif mode == "retrieval":
            records = asyncio.run(
                _run_db_cases(
                    bundle,
                    with_answer=False,
                    top_k=args.top_k,
                    seed_database=args.seed_db,
                )
            )
        elif mode == "answer":
            # Prefer DB answer path; fall back is not silent — infra error if DB down.
            records = asyncio.run(
                _run_db_cases(
                    bundle,
                    with_answer=True,
                    top_k=args.top_k,
                    seed_database=args.seed_db,
                )
            )
        else:  # pragma: no cover
            raise ValueError(f"Unknown mode {mode}")
    except InfrastructureError as exc:
        payload = {
            "error_class": "infrastructure",
            "error": str(exc),
            "hint": "Start disposable Postgres/pgvector (+ Redis/Ollama if needed) or use --mode fixture.",
        }
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return EXIT_INFRA
    except Exception as exc:
        payload = {
            "error_class": "application",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return EXIT_APP

    log_path = (
        Path(settings.RAG_EVAL_METRICS_LOG_PATH)
        if settings.RAG_EVAL_METRICS_LOG_PATH
        else None
    )
    for rec in records:
        append_metrics_log(log_path, rec)

    summary = _aggregate(records)
    summary["mode"] = mode
    summary["gold"] = str(args.gold)
    if args.summary_only:
        print(json.dumps(summary, indent=2))
    else:
        print(json.dumps({"summary": summary, "cases": records}, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
