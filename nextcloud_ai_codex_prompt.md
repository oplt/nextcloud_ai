# Codex implementation prompt — nextcloud_ai

Copy the prompt below into Codex while the `oplt/nextcloud_ai` repository is open. The companion audit contains source-linked evidence, but this prompt is self-contained.

---

You are the senior engineer responsible for repairing and improving `https://github.com/oplt/nextcloud_ai`. Implement the phased roadmap below in the repository. The audit was performed on `main` at commit `a5ddbc43a3d08fc8aa006132e9184444e845ec28`. First check the current commit, working tree, repository instructions, and any changes since that snapshot. Reproduce each reported issue against the current code; do not reintroduce a problem that has already been fixed.

The goals are reliable installation, correct permission enforcement, consistent ingestion/indexing, higher retrieval precision with useful recall, supported citations, bounded resource use, and simpler implementation code. Keep the existing FastAPI, PostgreSQL/pgvector, Celery, and React architecture unless measured evidence requires a particular boundary to move.

Proceed with implementation, not only a proposal. Work in the dependency order below, in small coherent changes. Complete the required validation for each phase before relying on it in later phases. Preserve unrelated user changes and existing public API behavior unless a correctness/security repair requires an explicitly documented change. Do not execute production migrations, bulk-delete user data, push changes, or deploy as part of local implementation. Record work completed and unresolved integration requirements truthfully.

## Non-negotiable implementation contracts

1. Every source read, including discovery, neighbors, graph expansion, fallback, and cached results, must enforce current identity/ACL, deletion state, hard document scope, and filters. Conversation history and previously cited IDs are not authorization.
2. Preserve original source spans independently from generated headings/context. Citations must point to actual supporting excerpts, not merely a related document.
3. Do not treat ranking values as calibrated probabilities. Zero is a valid model score. Never force a relevant-looking answer from an unanswerable scope.
4. Use one `AsyncSession` per concurrent task. Do not parallelize calls on a shared session or transfer ORM objects across sessions. Share clients only within a correctly owned process/event loop.
5. Cache keys must capture the data/model/permission versions that determine the answer. Caches must be bounded and invalidated safely.
6. Background work is at-least-once: make publication idempotent, version-aware, and coordinated with commit. Preserve a valid index while building its replacement.
7. Optimize measured expensive work and repeated algorithms. Prefer readable typed functions over code-golf, extra abstractions, or a wholesale rewrite.
8. Treat corpus text as evidence, not instructions. Keep model/system instructions separate, and verify claims conservatively.

## Phase 0 — Establish reproducible failures and trustworthy evaluation

Read `backend/pyproject.toml`, `backend/uv.lock`, `frontend/package.json`, both Compose files, `backend/Dockerfile`, migrations, tests, and active route/worker entrypoints. At the audited snapshot, the frozen Python install, Python compilation, nine backend tests, frontend build/lint, and Ruff F401/F811/F821/F841 checks passed. Those checks did not cover the failures below.

Use fixtures/fakes for fast tests and a disposable PostgreSQL/pgvector + Redis stack for integration tests when available. Do not use live credentials or modify a production corpus. Add a small seeded evaluation corpus with distractor documents, exact identifiers, tables, code, multi-page documents, multiple identities, and unanswerable questions. Include English and Dutch plus languages represented in the actual corpus.

Fix `backend/evals/run_offline_eval.py::_run_with_db`: it currently passes `expected_document_ids` into retrieval, leaking labels into the search scope. Gold IDs must only be used for scoring. Use a separate explicit request scope when the test question actually specifies one. It also scores concatenated excerpts as the answer; add an actual answer-generation/verification evaluation path and label retrieval-only runs accurately.

Fix metric definitions in `backend/evals/offline_scorer.py`: distinguish chunk/document units, deduplicate document IDs appropriately, report Recall@k, fixed-denominator Precision@k, MRR/nDCG, answer correctness, citation support, abstention, and stage latency. Keep any precision-over-returned metric separately named. Replace the three placeholder rows in `backend/evals/rag_gold.jsonl` with usable isolated fixtures or a documented fixture loader. Do not require arbitrary UUIDs from a user's production database.

Deliverable: reproducible baseline commands and a regression list tied to the phases below. Add suitable CI checks if the repository has none. Test failures must identify missing infrastructure separately from application failures.

## Phase 1 — Repair blockers and contain unsafe behavior

### 1A. Dependencies and deployment

- `backend/core/config.py` enables `RAG_TRUE_RERANK_ENABLED` by default. `backend/rag/cross_encoder_reranker.py` imports `sentence_transformers`, but the manifest/lock do not include it. Add a compatible locked dependency/extra and make Docker/local setup install the enabled feature. Add startup capability/readiness checks. Pre-provision models; do not download/load them inside the first normal request. Optional fallback must be explicit and observable.
- In `deployment/docker-compose.yml`, standardize `/app` and fully qualified commands: `backend.main:app`, `backend.scripts.seed_admin`, and `backend.workers.celery_app:celery_app`. Existing `main:app` and `workers.celery_app` commands fail relative imports. Reconcile development/production/local commands and use the lockfile in image installation.
- `backend/alembic/versions/00c7539a7dcd_generate_tables.py` assumes the vector extension already exists. Provide idempotent fresh-database extension initialization before applying migrations. Remove development bootstrap's runtime patching of migration source. Preserve applied migration history and add forward migrations for schema changes; explicitly document any minimal bootstrap compatibility repair.
- Restore missing `nc_ai_bridge/lib/` implementation referenced by `nc_ai_bridge/composer.json` and `appinfo/routes.php`. First search history/existing project files for the authoritative implementation. The root `.gitignore` rule `lib/` hides it; narrow that rule. If reconstruction is necessary, implement the existing backend signed handoff contract and test supported Nextcloud route/bootstrap behavior. Report unavailable integration evidence rather than claiming success without the PHP application.

### 1B. Authorization and webhook configuration

- Repair `backend/services/chat_service.py::ChatService._build_follow_up_neighbor_sources`, `_augment_follow_up_sources_with_neighbors`, and every other source augmentation path. They currently call `backend/db/repo/document.py::DocumentChunkRepository.list_by_document` without auth/scope. An isolated deleted-document fixture returned a source. Add an authorized bounded neighbor repository operation; pass one resolved scope through the entire flow. Recheck before prompt/delivery.
- Repair `backend/connectors/nextcloud/permissions.py::build_acl_for_path`, `_apply_share`, `schemas.py::ShareGrant`, `DocumentRepository.visibility_clause`, and `backend/services/authorization_service.py::document_is_visible_to_auth`. Any type-3 public link currently grants all app users access, even when permissions lack read. Do not equate a protected/possession-based link with global access. Enforce effective read bit, expiry and supported access proof; fail closed for unresolved grant types. Namespace external users/groups by trusted Nextcloud instance and prevent local username collisions. Verify inherited/federated grants against supported server behavior.
- `backend/connectors/nextcloud/webhooks.py::_verify_secret` currently allows unsigned requests when the secret is absent. Disable the endpoint or fail startup in non-development environments without its required secret. Reject bad/stale/replayed signatures and invalid payload shapes. `Settings.validate_security_settings` must reject placeholder production JWT/bridge secrets and unsafe bootstrap passwords, without breaking explicitly isolated test configuration.

### 1C. Immediate data-loss and UI fixes

- `backend/connectors/email/imap_client.py::AsyncImapClient._fetch_messages_sync` returns a bounded, possibly incomplete subset. `backend/services/email_sync_service.py::sync_connector` must not feed that subset into global deletion reconciliation. Separate complete authoritative UID inventory from bounded body fetching; use mailbox/UIDVALIDITY identity and explicit completeness. Failed fetches must retain existing indexed messages. Handle attachments consistently. Use read-only/`BODY.PEEK[]` semantics where supported to avoid changing message read state.
- Fix the jobs polling effect in `frontend/src/workspace/WorkspaceContext.tsx`. It depends on `jobs`, immediately calls `loadJobs`, and `loadJobs` replaces `jobs`, creating continuous fetches. Separate initial loading from polling or use a completion-based timer with stable dependencies; preserve visibility pause, request overlap protection, and cancellation on logout/unmount.
- Immediately remove blind citation attachment in `ChatService._verify_and_normalize_answer`. `_select_supporting_sources` discards the answer and `_answer_is_supported` mostly checks source existence/years. A source saying “Lunch is served at noon” currently auto-cites “The invoice total is EUR 999999.” Reject that case now; fuller verification is Phase 4.

Acceptance: clean deployment import smoke; enabled/disabled reranker modes; bridge package completeness; auth/revocation/delete/scope tests including retrieval-error fallback; unsigned webhook rejection; more-than-fetch-limit mail retention; partial fetch retention; fake-timer polling test; unrelated-evidence hallucination rejected.

## Phase 2 — Make indexing and jobs consistent

Repair these existing locations:

- `backend/services/nextcloud_sync_service.py::_upsert_document`: preserve parser/index metadata instead of replacing `metadata_json` with only `href`. Do not replace the content checksum with ETag. Apply the same metadata ownership rule to email/attachment upserts.
- `backend/services/indexing_service.py::ingest_document_bytes`, `_validate_file_metadata`: duplicate detection overwrites the checksum before testing current-index identity, and can keep old chunks when new bytes match another document. Compare current published indexed hash/fingerprint against the new payload before skipping. Reuse immutable artifacts across duplicates only with correct per-document chunk records/provenance/ACLs.
- `backend/ingestion/pipeline.py::ingest_document` and `DocumentChunkRepository.replace_for_document`: make one layer own status transitions; remove the repository's implicit `parsing` overwrite. Separate parse/lexical/vector readiness. Valid text must remain lexically searchable after embedding failure, and query embedding failure must not prevent lexical retrieval.
- `DocumentIngestionService._apply_product_intelligence_after_index` currently enqueues before commit. `enqueue_document_intelligence`'s one-second countdown is not a commit guarantee. Implement a transactional outbox, short publication transactions, versioned idempotency keys, and retryable dispatch. Cover commit-success/broker-failure as well as task-before-commit.
- Add document generation/source-version checks and a suitable lease/optimistic publication control for overlapping sync/reindex jobs. Stale workers must not overwrite a newer published index. Preserve prior valid content until replacement is ready.
- Repair database failure handling in Nextcloud/email sync: roll back a failed session before writing status, use a fresh transaction when necessary, and do not count unsupported/OCR/lexical-only outcomes as vector-indexed successes.
- Repair `backend/workers/indexing_tasks.py::_run_in_worker_loop`: never rerun an exhausted coroutine on arbitrary RuntimeError. Preserve original business exceptions and keep a stable loop/resource owner per worker process. Align `backend/workers/celery_app.py` signals and `backend/db/session.py` engine/client cleanup with that lifecycle.
- Replace `backend/main.py::lifespan`'s blanket `SyncJobRepository.reset_stale_running_jobs` behavior. Currently every running job is failed on API startup. Use lease/heartbeat expiry and atomic transitions that distinguish live workers from abandoned jobs.

Potential new modules: `backend/ingestion/index_versions.py`, `backend/workers/outbox_dispatcher.py`. Add real schema migrations, backfill/rollout documentation, and a rollback path. Do not bulk-delete/rebuild a user's active index during implementation.

Acceptance: repeat sync is metadata-preserving; A changes from X to Y while B already contains Y and A's chunks update; lexical-only ingestion is queryable during embedding outage; short text reaches its intended final status; old generations survive transient failures; concurrent/stale work cannot win; outbox redelivery is idempotent; failed-session handling works; RuntimeError is preserved; healthy jobs survive API restart.

## Phase 3 — Repair extraction, chunking, and embedding contracts

### Ordered parsing and provenance

In `backend/parsers/document_parser.py`:

- `parse_docx_bytes` currently collects all paragraphs then all tables. Preserve document body order, heading styles, and table positions.
- `parse_pdf_bytes` currently counts only nonempty extracted pages and extracts fields from the last page's `text`. Use the total physical page count and combined document text. Preserve original page numbers and handle empty/scanned/partially extracted pages explicitly.
- Avoid duplicating table content already included in page text when positional extraction can separate it reliably. Keep OCR-required and incomplete-extraction states honest.

In `backend/rag/parser.py`, carry section state across pages and preserve source offsets through whitespace normalization. Distinguish explicit headings, paragraphs, tables, lists, and fenced code; avoid discarding ordinary short sentences as headings. For code, preserve indentation, language and original line spans. Use language-aware function/class splitting for oversized blocks only where supported; do not flatten code into prose.

### Correct chunk emission

Repair `backend/rag/chunker.py::HeadingTableAwareChunker.chunk`, nested `flush`, `_block_with_context`, `_split_block`, and `backend/ai/chunker.py::chunk_parsed_document`:

- A 700-word paragraph plus a 200-word paragraph at size 850/overlap 100 currently emits a 900-word chunk because overlap retains a whole large block.
- Paragraph → table → end currently emits the paragraph again as an overlap-only final chunk.
- Context prefixes currently inherit table offsets and can generate spans beyond the actual source. Separate source span(s) and synthetic context fields.
- Enforce actual model-token limits including headings/context; keep overlap bounded, source order monotonic, and incompatible heading/page boundaries explicit. Emit no duplicate tail. Preserve table rows and repeat headers when splitting.

Define one canonical chunk/evidence object rather than duplicating fields through `ChunkDraft` and `RagChunkDraft` without purpose. Maintain compatibility at existing call sites during migration. Evaluate child/parent chunks using a small controlled parameter grid; 250–500-token children and 40–80-token overlap are starting hypotheses, not fixed optimal settings.

### Embeddings

Repair `backend/ai/ollama_embedding_client.py`, `backend/ai/embedding_client.py`, and `backend/ingestion/pipeline.py::_embed_in_batches`, `_embedding_input`:

- Validate output count, each dimension, finite numbers, and nonzero usable vectors. Verify active schema dimension/model compatibility at startup.
- Prevent silent input truncation; handle model context limits with explicit tokenizer/splitting rules. Document and query normalization must be deliberate and compatible; retain exact email/identifier text for lexical search.
- Version provider/model digest, dimension, tokenizer/preprocessing, parser, and chunker in the index fingerprint. Do not mix different model spaces just because dimensions match.
- Cache by normalized input hash plus fingerprint; reuse unchanged chunk embeddings. Batch by token/byte budget and bounded global/provider capacity. Retry transient failed batches, preserving successful batch work; do not throw away all vectors after one later batch fails.
- Introduce new index generations and switch only after complete validation. Document settings that require reindexing.

Acceptance: property-based chunk tests cover size/order/coverage/non-duplication/provenance; DOCX body order and PDF blank/final-page cases pass; table/code fixtures preserve structure; malformed/dimension-mismatched vectors fail clearly; model-version changes cannot silently reuse old embeddings; embedding failure/retry and staged reindex/rollback work.

## Phase 4 — Improve retrieval and grounded answers using evidence

### Lexical retrieval and document discovery

- Rewrite `backend/db/repo/document.py::DocumentChunkRepository.keyword_search`: `%term%` predicates with `ORDER BY chunk_index LIMIT ...` discard candidates before relevance ranking. Rank in SQL before limiting. Start with indexed weighted PostgreSQL full-text search, appropriate language/simple configurations, and exact/trigram identifier/filename matching. Label `ts_rank_cd` honestly rather than calling it BM25. Use a dedicated BM25 engine only if benchmarks justify its deployment cost.
- Refactor `backend/rag/stores.py::KeywordSearchStore.search`, `bm25_score_chunks`, `_chunk_tokens` to agree with the chosen lexical contract. Do not compute misleading corpus IDF over an arbitrary small candidate window. Exclude arbitrary internal JSON keys and base64 payloads; allowlist semantic fields.
- `DocumentRepository.search_documents` must limit distinct scored documents, not joined chunk rows. Use `EXISTS` or an ID-scoring subquery/CTE. `DocumentSearchService.search` must honor MIME and all filters. Score actual matched content instead of loading everything and examining only the first six chunks.
- Resolve hard scope before discovery in `ChatService.ask`. `is_document_discovery_query` must distinguish navigation from factual enumeration. “List all”/count queries need a completeness-aware plan or an explicit limitation, not an arbitrary top-k answer presented as exhaustive.

### One score contract and one final evidence selection

- Use rank-based fusion such as RRF in `backend/rag/retriever.py::HybridRetriever.retrieve`/`_merge_candidates`. Preserve separate raw scores/ranks and one deterministic candidate identity.
- Fix `backend/rag/stores.py::RetrievalCandidate.score` to distinguish `None` from zero. A zero rerank score must remain zero.
- Remove query-local min/max confidence from `CrossEncoderReranker._normalize_scores`. At present `[-20,-19]` becomes `[0,.999]` and a singleton becomes `.5`. Follow the chosen model's actual output contract and calibrate relevance/abstention on held-out negatives. A sigmoid is not automatic calibration.
- Do not concatenate a reranked head and heuristic tail as if scores are comparable. Rerank the final chosen window consistently; define a separate, observable fallback contract when inference is unavailable.
- Simplify `RetrievalService._select_grounded_chunks`: remove unconditional below-threshold scoped fallback and broad metadata bypasses that manufacture positive evidence. Preserve supported semantic matches and exact identifiers, calibrate document diversity, and test hard negatives.
- Remove/reconcile subsequent lexical reranking in `backend/ai/rag_postprocess.py` so it cannot silently undo the chosen final ranker.

### Context packing and verification

- In `ChatService.ask`, perform authorized expansion and deduplication before one final packing pass. Current compression precedes several augmentation passes and therefore does not bound the final prompt.
- Implement a token-aware packer, potentially `backend/rag/context_packer.py`, budgeted against the generation model: instructions + question + history + memory + evidence + output allowance + margin. Preserve rows/code/evidence spans; assign citation IDs after packing and keep mappings stable.
- Replace `ChatService._answer_is_supported`, `_select_supporting_sources`, `_verify_and_normalize_answer` with explicit citation-validity and claim-support checks, potentially `backend/rag/evidence_verifier.py`. Validate amounts/currency, dates/ranges, entities and qualifiers. For general claims, use conservative span evidence or a separately evaluated verifier. Correct unsupported claims from evidence or abstain. Do not just attach citations because some source exists.
- Keep a simple extractive fallback for model outages and record its actual mode. Ensure untrusted document text cannot change orchestration or access rules.

Acceptance: unscoped gold retrieval with distractors; late-chunk and exact-identifier cases; identical scope across all branches; singleton/zero/tie/negative rerank cases; unrelated evidence abstention; wrong entity/amount/unit/negation tests; multilingual and follow-up cases; full-prompt budget tests after augmentation; supported citation mapping. Report quality metrics and actual generation results before/after; explain tradeoffs instead of asserting every change improves precision.

## Phase 5 — Optimize measured bottlenecks

### Resource ownership and caching

Introduce a lifecycle owner, potentially `backend/core/ai_resources.py`, for the API process and separately for each worker process. Update `backend/main.py::lifespan`, service constructors, factories, and worker init/shutdown.

- Reuse/close HTTP clients; load the reranker once per appropriate process. Do not construct a heavyweight model inside every `RetrievalService._run_retrieval`/`HybridRetriever` instance. Offload model construction and bound prediction concurrency. Use a separate inference process only if GPU/RAM/concurrency measurements justify it.
- Share bounded caches at useful lifetimes rather than constructing `OllamaLLMClient._TTLCache` for each request. Add single-flight fills, TTL/LRU eviction, metrics, and mutation invalidation. Embedding cache keys need exact input+fingerprint; retrieval/answer caches additionally need auth/permission generation, full scope/filters, corpus/index version, ranking settings, prompt/model/options, and packed evidence identity. Revalidate authorization before delivery.
- Do not share current mutable `last_usage` among concurrent requests. Return structured generation/usage data or keep a per-request facade.
- Repair `ProductIntelligenceService._overview_cache` and `build_overview`: bound entries, invalidate permission/content/task changes, compute totals with SQL over all visible documents, and paginate details separately. The existing first-200-documents loop is not a global total.
- In `OllamaLLMClient.generate`/`ResilientLLMClient.generate`, preserve typed timeout/HTTP/validation failures, retry only transient failures with a total deadline and jitter, and disable ordinary production stub fallback. Chat must recognize the actual failure type and mode.

### Database and async work

- Audit mapper-level `lazy='selectin'` collections in `backend/db/models.py`. Use projections and explicit endpoint load plans; consider `lazy='raise'` to catch accidental loads. Do not replace them all with lazy selects and introduce new N+1 problems.
- Stop loading all messages for `ChatSessionRepository.list_by_user` summaries. Defer vectors/large metadata when unused. Replace repeated chat `list_by_document` reads and chunk-map reconstruction with authorized batched range queries and one request cache. Batch connector/version/chunk-health/job reads in sync and use SQL aggregates for counts.
- `parse_document_bytes` currently executes synchronous parsers inside async code. Use a bounded executor or worker process with resource/input limits. Choose threads versus processes using measured I/O/CPU behavior; cancellation of a waiting coroutine does not terminate a parser thread.
- Replace one-coroutine-per-file `gather` patterns in sync with bounded producer/consumer queues. Limit total provider/database work across workers, not merely per client. Amortize progress persistence. Avoid synchronous Celery ping in request handling; use explicit local mode or an independently refreshed status.
- Lexical/vector calls may use a single SQL operation or independent sessions when concurrency demonstrably helps. Never share one `AsyncSession` in `gather`.
- Benchmark `DocumentChunk`'s IVFFlat index against exact authorized retrieval. Existing 100 lists created before loading and default probes are not a universal configuration. For a growing corpus, benchmark HNSW; retain exact search for small/selective scopes. If using IVFFlat, train/rebuild after representative loading and tune lists/probes. Use supported iterative scans/filter indexes and preserve ACL predicates inside retrieval SQL. Pin supported pgvector behavior and provide forward migrations.

Measure p50/p95/p99 latency, throughput, event-loop lag, model loads, connection counts, SQL statement/row counts, memory, cache hit rate and authorized Recall@k. Establish representative workloads before setting hardware-dependent targets. Do not claim a speedup without measurements or trade accuracy for speed without reporting it.

## Phase 6 — Simplify code, remove verified dead paths, and prepare rollout

At the audited snapshot `ChatService` is 2,725 lines and `ask()` is 525 lines. `ProductIntelligenceService` is 1,402 lines and `_build_tasks()` is 314 lines. Extract cohesive components after behavior tests: query planner, scoped retrieval, packer, answer generator/verifier, chat persistence, typed intelligence extractors/task policies, and durable delivery. Keep the active path easy to trace.

Centralize retrieval scope/filter construction and the duplicated `_json_text` implementations in `backend/rag/stores.py`, `backend/rag/reranker.py`, and `backend/services/document_search_service.py` into an allowlisted/precomputed search representation. Consolidate chunk metadata types where justified. Replace repeated scans with sets/maps, precompute field normalization outside hot loops, and use data-driven policies for repeated task/extractor decisions without obscuring domain logic.

Review these no-in-repository-reference candidates and remove/deprecate only after checking routes, dynamic imports, scripts, external compatibility, and queued tasks:

- `frontend/src/App.css`, `frontend/src/assets/react.svg`, `frontend/src/pages/ChatPage.tsx`, empty root `package-lock.json`.
- `backend/services/conversational_rag_service.py` (unused alternative orchestration).
- `backend/db/repo/uow.py`: adopt it as a real transaction boundary or remove; do not keep an unused competing pattern.
- Compatibility re-exports `backend/connectors/nextcloud/nextcloud_client.py`, `nextcloud_events.py`, `nextcloud_permissions.py`, `nextcloud_sync.py`.
- `backend/workers/indexing_tasks.py::_run_logged_background_task`, `backend/db/session.py::run_async_safe`, `ProductIntelligenceService._classify_document`, `OfflineEvalRow`.
- `ChatService._source_evidence_lines`, `_entity_match_score`; `EvidenceExtractor.field_value_extractor`, `table_row_extractor`.
- Compatibility helpers `query_writer.is_likely_follow_up`, `build_retrieval_query`, `document_parser.parse_odt_bytes`, `rag_postprocess.compress_sources_for_prompt`, `prompt_builder.available_domain_profiles`.
- `cleanup_stale_connections` is a registered no-op Celery task: preserve through a drain/deprecation period if external or queued invocations may exist.

Do not delete framework entrypoints, validators, migrations, CLI scripts, package initializers, or registered tasks merely because static callers are absent. `frontend/public/vite.svg` is referenced by `frontend/index.html`; replace the reference before removal. `ai/chunker.py` and its fallback are active, not dead by association.

Finish with fresh-install and existing-database upgrade tests, relevant backend tests, frontend build/lint/timer tests, clean dependency installation, real-model/Nextcloud/IMAP integration smoke where infrastructure exists, and staged reindex quality comparison. Document migration, model provisioning, index fingerprints, outbox recovery, cache invalidation, rollback, and operational limits. Promote an index only after validation; no silent destructive rebuilds.

## Completion report

Return:

1. A phase-by-phase table of implemented changes, with actual file/function names.
2. Regression/integration/quality/performance commands and real results; distinguish tests run, unavailable infrastructure, and remaining hypotheses.
3. Database/index/configuration changes, data backfills and reindex requirements, and rollback instructions.
4. Files/helpers removed, compatibility items retained, and why.
5. Any unresolved issues with the concrete reason and next action.

Continue through the authorized local work. Do not stop after formatting, creating a plan, or silencing errors; the behavioral contracts and regression cases are the completion criteria.
