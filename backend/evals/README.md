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

# DB-backed retrieval (disposable Postgres/pgvector). Exit 2 = infra missing.
cd backend && PYTHONPATH=.. uv run python -m backend.evals.run_offline_eval --mode retrieval --summary-only

# Retrieval + answer generation/verification (needs DB + LLM/stub)
cd backend && PYTHONPATH=.. uv run python -m backend.evals.run_offline_eval --mode answer --summary-only

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
| stage_latency_seconds | per-stage timings |

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
| P4-* | Lexical rank, fusion, verification, packing | 4 |
| P5-* | Resource ownership / caching / DB load | 5 |
| P6-* | Dead path cleanup / rollout docs | 6 |

Re-run `make eval-fixture` after each phase that touches retrieval or answering.
