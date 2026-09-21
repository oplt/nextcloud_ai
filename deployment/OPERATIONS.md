# Operations Runbook

## Backups

Create a compressed PostgreSQL dump:

```bash
make deploy-backup-db
```

Restore a dump:

```bash
make deploy-restore-db BACKUP_FILE=deployment/backups/postgres-YYYYMMDD-HHMMSS.sql.gz
```

If you prefer a direct script call:

```bash
bash deployment/scripts/backup_postgres.sh
bash deployment/scripts/restore_postgres.sh deployment/backups/postgres-YYYYMMDD-HHMMSS.sql.gz
```

## Upgrades

1. Pull or copy the new release onto the host.
2. Create a backup first.
3. Review `backend/.env` for any new variables.
4. Rebuild and restart:

```bash
make deploy-up
```

5. Verify:

```bash
curl -fsS https://YOUR_HOST/health
curl -fsS https://YOUR_HOST/metrics | head
```

The backend container already runs `alembic upgrade head` on startup, so schema migrations apply automatically during upgrade.

## Webhook Registration

Register the webhook against the backend endpoint:

```text
POST https://YOUR_HOST/api/v1/nextcloud/webhooks
```

Recommended settings:

- Use a dedicated Nextcloud app password for the connector account.
- Set `NEXTCLOUD_WEBHOOK_SECRET` in `backend/.env` and configure the same secret in Nextcloud.
- Send `X-Webhook-Signature: sha256=<hmac>` over the raw body and `X-Webhook-Timestamp` (unix seconds) or `timestamp` in JSON.
- Keep `NEXTCLOUD_WEBHOOK_DEBOUNCE_SECONDS` non-zero to suppress event storms.
- Staging/production refuse to start without a non-placeholder webhook/JWT/bridge secret.

Unsigned requests are rejected. Missing secret disables the endpoint (HTTP 503).

## ACL / identity namespace

Nextcloud principals are stored as `nc:<instance>:user:<uid>` / `nc:<instance>:group:<gid>`.
Public/possession-based links never grant corpus-wide read to authenticated app users.
After upgrading, re-sync Nextcloud connectors so ACL rows are rewritten with namespaced IDs.

## Bridge Auth Setup

For the optional Nextcloud bridge app (`nc_ai_bridge/`):

1. Set identical `NEXTCLOUD_BRIDGE_SHARED_SECRET` values in the backend and Nextcloud bridge app config.
2. Point the bridge app to the public FastAPI base URL.
3. Keep clocks in sync; the bridge token TTL is short and replay-protected.

The PHP implementation lives under `nc_ai_bridge/lib/` (tracked; do not rely on a broad root `lib/` gitignore). Required files:

- `lib/AppInfo/Application.php`
- `lib/Controller/PageController.php`
- `lib/Controller/AuthController.php` (issues HS256 bridge tokens matching backend `BridgeTokenCodec`)

## Database bootstrap (pgvector)

Fresh Postgres volumes load `deployment/postgres-init/01-vector.sql` via `docker-entrypoint-initdb.d`.
Alembic also runs `CREATE EXTENSION IF NOT EXISTS vector` in:

- `00c7539a7dcd_generate_tables` (fresh installs)
- `a1b2c3d4e5f6_ensure_vector_extension` (already-migrated DBs)

Do not patch Alembic revision source at container start.

## True reranker

Default `RAG_TRUE_RERANK_ENABLED=true` requires the `rerank` extra (`sentence-transformers`).
Docker/local install includes it. Preload happens in API lifespan (`RAG_TRUE_RERANK_PRELOAD`).

```bash
# Explicit pre-provision (avoids first-request download)
python -m backend.scripts.provision_rerank_model
# Optional image bake: docker build --build-arg BUILD_RERANK_MODEL=1 ...
```

Fallback modes:

- `RAG_TRUE_RERANK_FALLBACK=heuristic` (default): degraded readiness, heuristic scores, observable in `/api/v1/health/ready` → `rerank`
- `RAG_TRUE_RERANK_FALLBACK=fail`: not ready; set `RAG_TRUE_RERANK_FAIL_STARTUP=true` to abort boot

## Secret Rotation

Rotate these values on a schedule:

- `JWT_SECRET_KEY`
- `SETTINGS_VAULT_KEY`
- `NEXTCLOUD_BRIDGE_SHARED_SECRET`
- `NEXTCLOUD_WEBHOOK_SECRET`

Rotation procedure:

1. Generate new values.
2. Update `backend/.env`.
3. Restart with `make deploy-up`.
4. Re-register or reconfigure bridge/webhook clients if they cache the old secret.

Rotating `SETTINGS_VAULT_KEY` invalidates encrypted connector secrets. Re-enter connector app passwords after rotation.

## Connector Credential Rotation

1. Create a fresh Nextcloud app password for the connector service account.
2. Open the Admin or Connectors UI.
3. Update the connector secret and save.
4. Run `Test` and then `Sync`.
5. Confirm a successful job in the Jobs page and check `/metrics` or audit logs if needed.

## Observability (metrics & alerts)

- Scrape `https://YOUR_HOST/metrics` with Prometheus (or poll manually with `curl` during incidents).
- RAG-specific series include `nextcloud_ai_rag_embedding_seconds_*`, `nextcloud_ai_rag_retrieval_sources_returned_*`, `nextcloud_ai_rag_verification_decisions_total`, `nextcloud_ai_rag_stage_errors_total`, and related counters documented in [deployment/grafana/RAG_DASHBOARD.md](grafana/RAG_DASHBOARD.md).
- Import [deployment/prometheus/rules_rag.yml](prometheus/rules_rag.yml) into your Prometheus `rule_files` and route alerts through Alertmanager.

## Data retention & privacy (operator assumptions)

**Chat messages and sessions**

- Chat content lives in Postgres (`chat_messages`, `chat_sessions`). There is no automatic TTL in the application layer today: plan retention (export + delete) according to your compliance policy.
- Session `memory_json` (structured memory, focus locks, optional `session_summary`) is stored on `chat_sessions` and cleared when the user uses “clear session memory” or equivalent API flags. Operators should treat it like other PHI/PII in the database backup scope.

**Webhooks and outbound hooks**

- Nextcloud webhooks should use `NEXTCLOUD_WEBHOOK_SECRET`; reject unsigned callbacks in production.
- Optional `TASK_WEBHOOK_URL` receives task payloads (title, document id, metadata). Payloads may include filenames and operator labels: use HTTPS, mutual TLS, or an allowlisted egress proxy. Redact or disable webhooks in strict environments.

**AI providers (Ollama / future HTTP LLMs)**

- Query text and retrieved snippets are sent to the configured embedding and chat endpoints. Document content is not sent to third-party SaaS unless you explicitly configure such a provider.
- Enable Sentry (`SENTRY_DSN`) only with `send_default_pii=false` (default in code) and a data-processing agreement appropriate for your region.

**Audit logs**

- Admin audit entries record user id, action, and resource identifiers. Retain or purge in line with the same policy as application DB backups.

## Operator review shortcuts (UI)

- **Admin → Operator review** links jump to failed/active jobs, intelligence, and documents.
- **Jobs** supports `?status=failed|active|completed|all` in the URL for bookmarking triage views.

## Frontend bundle hygiene

- Production build uses Vite `manualChunks` to split React, MUI, and app code for better caching. Run `npm run build` in CI and watch the reported chunk sizes after dependency upgrades.

## Phase 2 — Index generations, job leases, outbox

**Migration:** `b2c3d4e5f6a7_index_generations_job_leases_outbox`

- Adds `documents.index_generation` / `published_generation` for optimistic publish (stale workers cannot overwrite a newer generation).
- Adds `sync_jobs.lease_owner` / `lease_expires_at` / `last_heartbeat_at`. API startup only fails jobs whose lease expired — healthy workers survive restart.
- Adds `work_outbox` for post-commit intelligence dispatch. Beat tasks: `dispatch_work_outbox` (15s), `fail_expired_job_leases` (60s).

**Config**

- `SYNC_JOB_LEASE_SECONDS` (default 120): heartbeat TTL while a sync job runs.

**Rollout**

1. Backup DB.
2. `alembic upgrade head` (applies `b2c3d4e5f6a7`).
3. Restart API + workers + beat.
4. No bulk reindex required. Optional: re-run intelligence for docs indexed before outbox existed.

**Rollback**

1. Stop beat/workers writing outbox.
2. `alembic downgrade a1b2c3d4e5f6` (drops outbox + lease/generation columns).
3. Pending outbox rows are lost; re-extract intelligence if needed.

**Content checksum vs ETag**

- Nextcloud ETag is stored as `version_tag` / `metadata_json.etag` only. Content `checksum` is SHA-256 of payload bytes set during ingest. Repeat sync merges `metadata_json` and preserves parser/index fields.

## Phase 3 — Parse / chunk / embed contracts

- DOCX body walks document order (paragraphs + tables interleaved). PDF `page_count` is physical pages; blank pages retained; fields extracted from combined text.
- Chunker `title-token-v2`: overlap is word-bounded (not whole oversized blocks); table context is synthetic metadata; source spans stay on real text.
- Embedding fingerprint (`provider|model|dim|preprocessor|parser|chunker`) is stored on chunk metadata. Changing `EMBEDDING_DIM`, embedding model, or chunker version requires a staged reindex — do not mix vector spaces.
- Partial batch embedding failures keep successful vectors; failed slots stay null with `embedding_status=partial` / `lexical_ready` as appropriate.
- Unchanged chunks reuse prior vectors when `content_hash` + fingerprint match (no silent cross-model reuse).
- Oversized inputs are **split then mean-pooled** — never silently truncated. Tunables: `EMBEDDING_MAX_INPUT_CHARS`, `EMBEDDING_BATCH_MAX_CHARS`.
- API startup runs `verify_embedding_runtime_compat()` (dim probe). Set `EMBEDDING_COMPAT_REQUIRED=true` to fail closed when the live model disagrees with `EMBEDDING_DIM`.

## Phase 4 — Lexical retrieval

- Chunk keyword search ranks with PostgreSQL `ts_rank_cd` (`simple` config) **before** `LIMIT`. That score is cover density, not BM25.
- Identifier-like terms (emails, mixed alphanumerics) also match via `ILIKE` and add a fixed boost. Do not treat the boost as BM25.
- Migration `c3d4e5f6a7b8` adds `pg_trgm`, a GIN index on chunk content `to_tsvector('simple', content)`, and a trigram index on `documents.file_name`.
- Document discovery limits **distinct documents** by best chunk rank. `list all` / `how many` answers include the matched total and say when the shown page is incomplete.
- Navigation discovery runs only when no explicit document ids, focus lock, or filename scope is set.

## Phase 4 — Score contract

- Hybrid fusion is **RRF** (`k=60`). Raw semantic/keyword scores and 1-based ranks stay on the candidate; `fused_score` is the RRF sum.
- `RetrievalCandidate.rerank_score` is `None` until a final ranker runs. A zero rerank score stays zero (no `or`-coercion to fused).
- Cross-encoder scores use sigmoid on logits — no query-local min/max. Singleton logit `0` → `0.5`; tight negative pairs stay near zero.
- True rerank scores the chosen window only. Heuristic fallback is separate and observable via `true_rerank_fallback`; unscored tails are not concatenated as comparable scores.
- Grounded selection abstains when nothing clears the floor. No below-threshold scoped fallback; exact identifiers may pass the relative floor.
- `rerank_and_truncate_sources` no longer reorders by lexical overlap after the final ranker.

## Phase 4 — Context packing and verification

- `ChatService.ask` expands, re-authorizes, and dedupes sources **before** one `pack_evidence_for_prompt` pass. Citation IDs are assigned after packing.
- Prompt budget: `RAG_PROMPT_CONTEXT_TOKENS` minus instructions/question/history/memory/output reserve/margin. Tunables in `.env.example`.
- `evidence_verifier` checks citation indexes, amounts/currency, dates, entities, and span overlap. Unsupported claims abstain (or shadow-keep).
- LLM outages use extractive snippets; `verification.answer_mode` records `extractive_llm_timeout` / `extractive_llm_outage` / `extractive_empty_llm`.

## Phase 5 — Resource ownership

- `backend/core/ai_resources.py` owns process LLM/embedding clients and `AsyncTTLCache` (TTL/LRU + single-flight). Started from API `lifespan` and Celery `worker_process_init`; closed on shutdown.
- Cross-encoder remains process-owned via `rerank_runtime` (preload once; not per retrieve).
- LLM usage is task-local (`ContextVar`); do not share mutable `last_usage` across concurrent requests.
- Staging/production never attach the stub LLM fallback even if `LLM_FALLBACK_PROVIDER=stub`.
- Ollama generate retries only transient failures (timeouts/5xx/429) with deadline + jitter; validation/HTTP 4xx raise typed errors.
- Intelligence overview totals come from authorized SQL aggregates; spotlight is a separate page. Overview cache is TTL + max 64 entries and clears on intelligence rebuild.

## Phase 5 — Database and async

- Hot collections (`Document.chunks` / insights / tasks, `ChatSession.messages`) use `lazy="raise"`. Endpoints must `selectinload` (or projections); chat list uses subject/count subqueries without loading message bodies.
- Chunk reads defer `embedding` unless needed. Document detail `chunk_count` is an SQL count, not `len(chunks)`.
- `parse_document_bytes` runs sync parsers on a bounded 2-worker thread pool (80MB input cap). Cancelling the await does not kill the worker thread.
- Nextcloud sync uses a bounded queue (`NEXTCLOUD_SYNC_INGEST_CONCURRENCY`) with amortized progress commits (`NEXTCLOUD_SYNC_PROGRESS_EVERY`). Each item opens its own DB session — never share one `AsyncSession` across `gather`.
- `CELERY_LOCAL_MODE=auto|never|always`: production/staging never ping the broker on the request path; `auto` caches a 0.5s inspect ping only in development.
- IVFFlat (`ix_document_chunks_embedding_ann`, lists=100) is not a universal default. Runtime sets `ivfflat.probes` via `PGVECTOR_IVFFLAT_PROBES` on broad ANN queries. Small authorized document scopes use exact distance ordering. Rebuild/train after representative load; evaluate HNSW with benchmarks before swapping — do not claim a speedup without measurements. See Alembic `d4e5f6a7b8c9`.

## Phase 6 — Simplify and rollout

### Removed (verified unused)

- `frontend/src/App.css`, `frontend/src/assets/react.svg`, `frontend/src/pages/ChatPage.tsx`, empty root `package-lock.json`
- `backend/services/conversational_rag_service.py`
- `backend/db/repo/uow.py` (unused competing UnitOfWork)
- `run_async_safe`, `_run_logged_background_task`, `ProductIntelligenceService._classify_document`
- Dead chat helpers: `ChatService._source_evidence_lines`, `_entity_match_score`; `EvidenceExtractor.field_value_extractor`, `table_row_extractor`

### Extracted / centralized

- `EvidenceExtractor` / `EvidenceMatch` → `backend/rag/evidence_extractor.py` (active path still via `ChatService`)
- Shared `retrieval_filter_kwargs` in `backend/rag/stores.py`
- Reranker uses allowlisted `semantic_json_text` (no local `_json_text`)
- `OfflineEvalRow` **kept** — active eval contract

### Deprecated (compat retained one release)

- `connectors/nextcloud/nextcloud_*.py` re-exports (DeprecationWarning)
- `query_writer.is_likely_follow_up`, `build_retrieval_query`
- `document_parser.parse_odt_bytes`, `rag_postprocess.compress_sources_for_prompt`, `prompt_builder.available_domain_profiles`
- Celery task `cleanup_stale_connections` — registered no-op; not on beat schedule. Drain external queues before deleting.

### Rollout checklist

1. `alembic upgrade head` (includes vector extension + ANN comment migration `d4e5f6a7b8c9`). No silent index rebuild.
2. Provision rerank model if needed: `python -m backend.scripts.provision_rerank_model`.
3. Confirm embedding fingerprint / `EMBEDDING_DIM` before promoting a new index generation.
4. Outbox: beat task `dispatch-work-outbox` every 15s; failed leases via `fail-expired-job-leases`.
5. Cache: AI resource TTL cache + intelligence overview cache clear on rebuild.
6. Rollback: revert app image; DB migrations are additive (extension/comment). Do not drop IVFFlat without a measured replacement.
7. After deploy: compare offline eval / staged reindex Recall@k before promoting a new generation.