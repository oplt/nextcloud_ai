# Offline RAG evaluation — Phase 0 baseline

Isolated fixtures under `fixtures/` seed a small multilingual corpus with
distractors, tables, code, multi-page docs, ACL identities, and unanswerable
questions. Gold `expected_*` IDs are **scoring-only**. Only
`request_document_ids` may scope retrieval.

## Commands

From repo root:

```bash
make eval-fixture
make eval-structure
make test-backend-unit

# Equivalent:
cd backend && PYTHONPATH=.. uv run python -m backend.evals.run_offline_eval --mode fixture --summary-only
cd backend && PYTHONPATH=.. uv run python -m backend.evals.run_offline_eval --mode structure --summary-only

# DB-backed retrieval with fixtures flushed in a rollback-only transaction.
# --seed-db refuses non-local and staging/production databases.
cd backend && APP_ENV=test EMBEDDING_PROVIDER=deterministic RAG_TRUE_RERANK_ENABLED=false PYTHONPATH=.. uv run python -m backend.evals.run_offline_eval --mode retrieval --seed-db --summary-only

# Retrieval + answer generation and production evidence verification
# (needs DB + configured LLM; only verifier-approved citations are scored)
cd backend && PYTHONPATH=.. uv run python -m backend.evals.run_offline_eval --mode answer --summary-only

# Controlled chunk size/overlap grid and repeatable offline resource baseline.
cd backend && PYTHONPATH=.. uv run python -m backend.evals.chunk_grid
cd backend && PYTHONPATH=.. uv run python -m backend.evals.performance_benchmark --iterations 25

# Phase 5 measured bottlenecks (disposable Postgres):
make phase5-db-benchmark
make phase5-ann-benchmark
make phase5-concurrency-smoke

# Unit/regression tests (scorer + harness; no live credentials)
cd backend && PYTHONPATH=.. uv run pytest tests/test_offline_scorer.py tests/test_offline_eval_harness.py tests/test_chat_direct_answer.py -q

# Broader quality gate used by CI / local
make check
make eval-fixture
make test-backend-unit
```

Exit codes:

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Application / evaluation failure |
| 2 | Infrastructure missing (DB/Redis/network) |

## Fixture loader

- `fixtures/corpus.json` — documents + chunks
- `fixtures/identities.json` — alice / bob / admin
- `rag_gold.jsonl` — questions referencing `doc:...` / `chunk:...` keys
- `fixture_loader.fixture_uuid(key)` — stable UUIDv5 (no production DB IDs)

## Metrics (`offline_scorer.py`)

| Metric | Definition |
|--------|------------|
| Precision@k | hits in top-k / **k** (fixed denominator) |
| precision_over_returned@k | hits / returned (separate name) |
| Recall@k | \|relevant ∩ top-k\| / \|relevant\| |
| MRR | 1 / rank of first relevant |
| nDCG@k | binary relevance |
| answer_correctness | required term coverage |
| citation_support | cited ∩ gold / cited |
| abstention | unanswerable/answerable behavior |
| stage_latency_seconds | retrieval, answer generation, and verification timings |

Summaries include mean plus p50/p95/p99 stage latency. Retrieval relevance
metrics exclude unanswerable/ACL-denied rows with no gold document; those rows
are scored by abstention and exclusion metrics instead of being counted as
false retrieval misses.

Document rankings dedupe by first occurrence; chunk rankings keep duplicates.

## Regression list (tied to phases)

| ID | Failure | Phase |
|----|---------|-------|
| P0-E1 | Gold `expected_document_ids` leaked into `retrieve(document_ids=...)` | 0 (fixed) |
| P0-E2 | Concatenated excerpts scored as “answer”; retrieval-only unlabeled | 0 (fixed) |
| P0-E3 | Precision@k used returned-count denominator; no R@k/MRR/nDCG | 0 (fixed) |
| P0-E4 | Placeholder gold rows without fixture corpus | 0 (fixed) |
| P1-A1 | Reranker enabled without locked `sentence_transformers` | 1A (fixed: `rerank` extra + preload/fallback) |
| P1-A2 | Compose module paths / migration vector extension | 1A (fixed) |
| P1-A3 | `nc_ai_bridge/lib/` hidden by root `lib/` gitignore | 1A (fixed; package restored) |
| P1-B1 | Neighbor expansion without ACL (`list_by_document`) | 1B (fixed) |
| P1-B2 | Public link type-3 grants global access | 1B (fixed) |
| P1-B3 | Unsigned webhooks when secret absent | 1B (fixed) |
| P1-C1 | IMAP partial fetch → global deletion | 1C (fixed) |
| P1-C2 | Jobs polling infinite loop | 1C (fixed) |
| P1-C3 | Blind citation attachment / unrelated evidence | 1C (fixed) |
| P2-1 | NC upsert wipes metadata; ETag used as checksum | 2 (fixed) |
| P2-2 | Duplicate skip keeps wrong chunks / overwrites checksum early | 2 (fixed) |
| P2-3 | `replace_for_document` forces `parsing`; embed fail not lexical-searchable | 2 (fixed) |
| P2-4 | Intelligence enqueue before commit | 2 (fixed: outbox) |
| P2-5 | Stale workers / API restart kill healthy jobs | 2 (fixed: generations + leases) |
| P2-6 | Worker loop re-awaits exhausted coro on RuntimeError | 2 (fixed) |
| P3-1 | DOCX paragraphs-then-tables loses body order | 3 (fixed) |
| P3-2 | PDF page_count/fields from nonempty/last page only | 3 (fixed) |
| P3-3 | Chunk overlap emits oversized / duplicate tails | 3 (fixed) |
| P3-4 | Embedding silent truncation / no vector validation | 3 (fixed) |
| P4-1 | Lexical rank after LIMIT / fake BM25 IDF | 4 (fixed: SQL ts_rank_cd before LIMIT) |
| P4-2 | Score None≠0 / minmax / lexical undo / scoped fallback | 4 (fixed: RRF + sigmoid + grounded floors) |
| P4-3 | Blind citations / claim support | 4 (fixed: evidence_verifier) |
| P4-4 | Prompt packing after augmentation | 4 (fixed: one packer pass) |
| P4-5 | Uncalibrated abstention floors | 4 (fixed: held-out calibrate harness) |
| P4-6 | Document text injects orchestration/ACL | 4 (fixed: untrusted source framing + tests) |
| P5-1 | Per-request model/HTTP construction / shared last_usage | 5 (fixed: ai_resources + ContextVar) |
| P5-2 | Unbounded overview cache / first-200 totals | 5 (fixed) |
| P5-3 | Sync parsers on event loop / unbounded gather | 5 (fixed: parse pool + map_bounded) |
| P5-4 | Fixture-only performance numbers | 5 (fixed: phase5-db-benchmark) |
| P5-5 | IVFFlat without exact/HNSW measurements | 5 (fixed: phase5-ann-benchmark) |
| P5-6 | No concurrency capacity smoke | 5 (fixed: phase5-concurrency-smoke) |
| P6-1 | Dead paths / duplicate serializers | 6 (fixed earlier + inventory) |
| P6-2 | Oversized intelligence task builder in service | 6 (fixed: populate_from_insights) |
| P6-3 | Uninventoried shims / cleanup task | 6 (fixed: phase6-compat-inventory) |
| P6-4 | Format/build/rollout evidence missing | 6 (fixed: format + frontend build + rehearsal) |

Re-run `make eval-fixture` after each phase that touches retrieval or answering.

Phase 4 evidence commands: `make phase4-quality-compare`, `make phase4-threshold-calibrate`, `make phase4-injection-test`.
