# nextcloud_ai — repository audit and fixing roadmap

Repository: https://github.com/oplt/nextcloud_ai  
Reviewed: 21 September 2026  
Snapshot: `main` at `a5ddbc43a3d08fc8aa006132e9184444e845ec28` (commit dated 27 April 2026). All source links below are pinned to this snapshot.

The highest priorities are permission enforcement, successful installation/deployment, ingestion consistency, and evidence verification. More threads or a larger embedding model would not fix these defects. Preserve the existing FastAPI/PostgreSQL/Celery structure while correcting its contracts and ownership boundaries.

“Concise code blocks” is interpreted primarily as simplifying repeated and complex implementation code. Recommendations also cover preserving fenced code when documents contain technical examples.

## Scope and verification

Mapped the 225 tracked files and inspected the main ingestion, parser, embedding, retrieval, ranking, chat, authorization, sync, worker, deployment, and frontend paths. This is a source audit with isolated execution, not a production penetration test or a measured capacity benchmark.

| Check | Result |
|---|---|
| Frozen Python dependency install | `uv sync --frozen --extra dev` succeeded |
| Python compilation | `python3 -m compileall -q backend` passed |
| Existing backend tests | **9 passed**; these cover direct-answer/summary behavior |
| Frontend clean install, build, lint | Passed |
| Targeted Ruff checks | No F401, F811, F821, or F841 findings |
| Isolated behavior probes | 14 observations completed, including the failures described below |
| Live PostgreSQL/pgvector, Redis, Ollama, IMAP, Nextcloud | Not exercised end to end |
| Query plans, GPU capacity, concurrency/p95 performance | Not measured; performance recommendations require benchmarks |

No application source files were changed and no commits or PRs were created. The probes used local fixtures/mocks; they did not contact external application services. Passing compilation/lint does not establish runtime correctness.

Evidence labels: **Reproduced** means an isolated execution demonstrated the behavior. **Source-confirmed** means the control/query path establishes the defect, but its deployed manifestation was not run. **Benchmark required** means the code creates a plausible bottleneck or quality risk whose size remains unmeasured. Priorities: P0 = startup/security blocker; P1 = correctness, data integrity, or major availability; P2 = optimization and maintainability.

## Findings and recommended fixes

### F01 — Default reranking cannot run after a declared-dependency install

**P0 · Reproduced.** `RAG_TRUE_RERANK_ENABLED` defaults to true, but `sentence-transformers` is absent from both `pyproject.toml` and `uv.lock`. `HybridRetriever._get_true_reranker()` raises `ModuleNotFoundError: No module named 'sentence_transformers'` in the freshly installed environment. Normal retrieval reaches this import when there are candidates.

Files/functions: [backend/core/config.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/core/config.py#L91-L94), [backend/rag/retriever.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/rag/retriever.py#L43-L58) `HybridRetriever._get_true_reranker`; [backend/rag/cross_encoder_reranker.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/rag/cross_encoder_reranker.py) `CrossEncoderReranker.__init__`; [backend/pyproject.toml](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/pyproject.toml).

**Fix:** declare and lock a supported reranker dependency set, preferably an explicit installation extra that deployment actually installs. Validate enabled capabilities at startup, including model availability. Provision the model outside the first user request. An optional unavailable reranker may fall back to a measured baseline with an explicit degraded status; silently pretending reranking succeeded is inappropriate. Add a clean-install retrieval smoke test with a deterministic fake model and a separate real-model smoke test.

### F02 — Production commands use the wrong package layout; fresh database initialization is incomplete

**P0 · Reproduced for import failure; source-confirmed for migration setup.** Production Compose runs `uvicorn main:app`, `python -m scripts.seed_admin`, and `celery -A workers.celery_app:celery_app` from `/app/backend`. These modules use package-relative imports. Reproducing `import main` from that directory raises `ImportError: attempted relative import with no known parent package`. The backend Dockerfile already uses `backend.main:app`, so the production override regresses it.

The initial migration uses `VECTOR(1024)` without creating the vector extension. The development Compose bootstrap creates it, while the production command only runs Alembic. Installing the extension binaries in the database image does not activate the extension in each database.

Files: [deployment/docker-compose.yml](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/deployment/docker-compose.yml#L73-L176), [backend/Dockerfile](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/Dockerfile), [backend/alembic/versions/00c7539a7dcd_generate_tables.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/alembic/versions/00c7539a7dcd_generate_tables.py), [docker-compose.yml](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/docker-compose.yml#L60-L107).

**Fix:** standardize working directory/PYTHONPATH on `/app` and commands on `backend.main`, `backend.scripts.seed_admin`, and `backend.workers.celery_app`. Use reproducible locked installation in images. Add an explicit, idempotent extension initialization step before initial migrations; eliminate runtime editing of migration source. Verify a fresh volume and an upgrade of an existing database. Coordinate one migration job before starting API/worker services.

### F03 — The published Nextcloud bridge is missing its PHP implementation

**P0 for the bridge · Source-confirmed.** `composer.json` maps `OCA\\NcAiBridge\\` to `lib/`, and routes reference `page#index` and `auth#bootstrap`, but no `nc_ai_bridge/lib/` files are tracked. The root ignore rule `lib/` matches that directory. The repository cannot provide the advertised bridge controllers on a fresh installation.

Files: [nc_ai_bridge/composer.json](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/nc_ai_bridge/composer.json), [nc_ai_bridge/appinfo/routes.php](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/nc_ai_bridge/appinfo/routes.php), [nc_ai_bridge/appinfo/info.xml](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/nc_ai_bridge/appinfo/info.xml), [.gitignore](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/.gitignore#L149).

**Fix:** restore the authoritative controller/bootstrap/service files from an existing working installation or history, if available. Narrow the ignore rule or add an exception for this application directory. If the implementation truly is unavailable, implement against the backend's existing signed handoff contract with explicit expiry, replay protection, user identity, and CSRF requirements. Do not invent an incompatible SSO protocol. Add an installation/route-resolution test on a supported Nextcloud version.

### F04 — Follow-up expansion bypasses document visibility and hard query scope

**P0 · Reproduced with a deleted-document fixture.** `ChatService._build_follow_up_neighbor_sources()` and `_augment_follow_up_sources_with_neighbors()` read prior citation document IDs through `DocumentChunkRepository.list_by_document()`. That repository method has no `auth`, deletion, parse-status, or request-scope constraint. The probe returned a neighbor from a document marked deleted. A user who previously had access can therefore obtain new source content through this path after access changes; the normal search SQL's ACL checks do not protect this second read. Old citation references can also escape a newly requested document scope.

Files/functions: [backend/services/chat_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/chat_service.py#L607-L696), [backend/services/chat_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/chat_service.py#L2430-L2545), [backend/db/repo/document.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/repo/document.py#L448-L454).

**Fix:** introduce one immutable retrieval scope containing current identity, hard document scope, and filters. Require it for every candidate, neighbor, graph, discovery, and fallback read. Fetch only the required adjacent chunk ranges with an authorized document join. Recheck before prompt assembly and delivery. Add ACL-revocation, soft-delete, cross-user, and explicit-scope tests, including the retrieval-error fallback. Decide separately how previously delivered chat history is retained; it must never authorize fresh reads.

### F05 — Public-link existence is incorrectly treated as universal read permission

**P0 · Reproduced for a non-read public share.** `NextcloudPermissionService.build_acl_for_path()` sets `public_link_enabled` for every share of type 3. `DocumentRepository.visibility_clause()` then exposes it to every authenticated app user. `ShareGrant` omits password/expiration metadata and `_apply_share()` ignores the read bit. A public share with permissions `4` produced an ACL readable by an unrelated local user in the probe.

Files/functions: [backend/connectors/nextcloud/permissions.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/connectors/nextcloud/permissions.py), [backend/connectors/nextcloud/schemas.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/connectors/nextcloud/schemas.py#L25-L45), [backend/db/repo/document.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/repo/document.py#L289-L299), [backend/services/authorization_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/authorization_service.py#L125-L147), [backend/core/security.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/core/security.py) `auth_user_identifiers`.

**Fix:** do not turn possession-based link access into global corpus visibility. Require explicit supported access proof and honor effective read permissions, expiry, and protected-link semantics. Fail closed for unsupported federated/circle/Talk grant mappings. Namespace external user/group IDs by trusted Nextcloud instance; the current plain username/group matching can collide if multiple instances or local accounts share names. Validate inherited grants and revocation with real Nextcloud fixtures. These identity/inheritance cases are additional source-level risks, not live-server reproductions. Nextcloud documents distinct read/create bits and protected/expiring links in the [OCS Share API](https://docs.nextcloud.com/server/latest/developer_manual/client_apis/OCS/ocs-share-api.html).

### F06 — Webhook authentication and production secret validation fail open

**P0 when exposed with defaults · Source-confirmed.** `_verify_secret()` immediately returns when the webhook secret is absent; the route has no user authentication dependency. `NEXTCLOUD_WEBHOOK_SECRET` defaults to `None`. Production validation checks cookie settings but does not reject the known placeholder JWT/bridge secrets or default administrator password.

Files/functions: [backend/connectors/nextcloud/webhooks.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/connectors/nextcloud/webhooks.py) `_verify_secret`, `receive_nextcloud_webhook`; [backend/core/config.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/core/config.py) `Settings`, `validate_security_settings`; [backend/scripts/seed_admin.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/scripts/seed_admin.py).

**Fix:** fail startup or disable the webhook endpoint when its required secret is missing outside explicit development mode. Reject missing/invalid signatures, stale timestamps, and duplicate event IDs; validate payload shape and bound body size. Reject placeholder production secrets, and ensure account bootstrapping cannot deploy a known default password. Add default-configuration and authentication contract tests. This finding does not establish that any running deployment uses these defaults.

### F07 — Limited IMAP fetches incorrectly delete older indexed mail

**P1 · Source-confirmed.** `_fetch_messages_sync()` fetches only the last `fetch_limit` UIDs and skips failed fetches. `EmailConnectorSyncService.sync_connector()` then marks every document not in that successfully fetched subset deleted. With more than the configured limit (default 100), still-existing older messages and their attachments disappear from the index. A temporary fetch/parse failure can produce the same outcome. This is index deletion, not deletion of messages on the IMAP server.

Files/functions: [backend/connectors/email/imap_client.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/connectors/email/imap_client.py) `AsyncImapClient._fetch_messages_sync`; [backend/services/email_sync_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/email_sync_service.py#L29-L160) `sync_connector`; [backend/db/repo/document.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/repo/document.py) `mark_deleted_missing_from_external_ids`.

**Fix:** separate complete mailbox inventory from bounded content fetching. Track mailbox identity and UIDVALIDITY/UID checkpoints, enumerate authoritative current IDs or explicit expunges, and delete only when a complete inventory confirms absence. A partial/filtered fetch must never drive global deletion. Use a non-mutating fetch such as `BODY.PEEK[]` and read-only selection where possible; current `RFC822` fetching can mark messages seen. Add a mailbox fixture larger than the fetch limit plus partial failures and UIDVALIDITY changes.

### F08 — An unchanged sync erases ingestion metadata and replaces the content hash

**P1 · Reproduced.** `_upsert_document()` unconditionally assigns `metadata_json = {'href': ...}` and `checksum = etag`, before deciding whether to reindex. The unchanged-file branch then commits. The probe lost `ingestion_quality` and language metadata and replaced a content hash with an ETag. Email upserts also replace metadata and can drop previously added ingestion quality.

Files/functions: [backend/services/nextcloud_sync_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/nextcloud_sync_service.py#L223-L264) `_upsert_document`; [backend/services/email_sync_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/email_sync_service.py) `_upsert_email_document`, `_upsert_attachment_document`.

**Fix:** merge connector-owned metadata under its own namespace, preserving parser/classifier/index metadata. Keep remote ETag/version, downloaded SHA-256, and indexed-content hash in separate fields. Update the byte checksum only after obtaining bytes. An unchanged sync must preserve chunks, ingestion metadata, and embedding provenance.

### F09 — Duplicate detection can preserve stale chunks after a document changes

**P1 · Reproduced with repository fixtures.** `ingest_document_bytes()` first overwrites `document.checksum` with the new payload hash. If another indexed document has that hash and the current document already has usable chunks, it returns `duplicate_unchanged` without comparing the current index's old content hash. The probe changed the payload but made zero parser calls. Existing chunks can describe the previous content while metadata records the new hash.

Files/functions: [backend/services/indexing_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/indexing_service.py#L65-L90) `DocumentIngestionService.ingest_document_bytes`, `_validate_file_metadata`; [backend/db/repo/document.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/repo/document.py) `find_indexed_duplicate`.

**Fix:** short-circuit only when the current published index hash and full indexing fingerprint match the current payload. Cross-document deduplication may reuse immutable parse/embedding artifacts, but must create correct document-specific chunk records, provenance, and ACLs. Test A changing from X to Y while B already contains Y.

### F10 — Claimed lexical fallback is unavailable after embedding failure; repository writes overwrite status

**P1 · Source-confirmed.** Ingestion deliberately saves text chunks when embedding fails and marks the document `partially_parsed`. Both `semantic_search()` and `keyword_search()` default to `parse_status='indexed'`, hiding those fallback chunks. Separately, `RetrievalService.retrieve()` embeds the query before starting lexical search, so an embedding outage prevents the lexical branch entirely.

`replace_for_document()` also writes `parse_status='parsing'`. The short-text branch sets `needs_ocr`/`partially_parsed` and then calls this method without restoring the final status.

Files/functions: [backend/ingestion/pipeline.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/ingestion/pipeline.py#L35-L175), [backend/db/repo/document.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/repo/document.py#L436-L446), [backend/db/repo/document.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/repo/document.py#L456-L562), [backend/services/retrieval_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/retrieval_service.py#L98-L138).

**Fix:** separate parse, lexical readiness, and vector readiness. Make chunk replacement a persistence operation rather than a status owner. Allow lexical retrieval for valid extracted text with failed vectors. Continue lexical search when query embedding fails and report degraded mode. Preserve the last valid index generation on transient failures. Persist terminal failure status in a valid transaction and schedule failed-vector retries independently.

### F11 — Chunk overlap violates the size limit and duplicates text around tables

**P1 · Reproduced.** `HeadingTableAwareChunker.chunk()` retains at least one whole block in `flush()`, even when it exceeds the overlap allowance. With `chunk_size=850`, `overlap=100`, and 700-word/200-word paragraphs, it emits sizes **700 and 900**. Paragraph → table → end produced three chunks, with the first and last identical. Retained text can also cross section boundaries and be emitted out of source order.

`_block_with_context()` inserts synthetic context while keeping the original table offsets; the resulting `_split_block()` offsets can extend beyond the actual source table. Table splitting is word-based and can cut rows/headers.

Files/functions: [backend/rag/chunker.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/rag/chunker.py#L45-L104) `chunk`/nested `flush`; [backend/rag/chunker.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/rag/chunker.py#L106-L207) `_block_with_context`, `_split_block`; [backend/ai/chunker.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/ai/chunker.py) `chunk_parsed_document`.

**Fix:** make emission and overlap retention separate operations. Enforce the actual token budget after headings/context are added. Retain a bounded suffix, discard it at incompatible structural boundaries, and never emit an overlap-only final chunk. Track original evidence spans separately from generated context. Split tables by row groups with repeated headers. Add property-based checks for coverage, order, maximum size, non-duplication, and valid provenance.

### F12 — Extraction loses document order and some PDF metadata

**P1 · Reproduced.** `parse_docx_bytes()` reads all paragraphs, then all tables, moving tables away from their original context. The DOCX probe placed a middle table after the final paragraph. `parse_pdf_bytes()` sets `page_count` to the count of nonempty extracted pages and extracts financial fields from the final loop variable `text`, not the combined document. A two-page fixture with a blank last page reported one page and lost the first page's amount.

Further quality risks: PDF tables are appended after full page text, potentially duplicating table content; `RagParser` rebuilds its heading stack for each page; plain-heading heuristics can misclassify short sentences; no fenced-code block model exists.

Files/functions: [backend/parsers/document_parser.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/parsers/document_parser.py#L143-L197) `parse_pdf_bytes`, `parse_docx_bytes`; [backend/rag/parser.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/rag/parser.py) `normalize`, `_blocks_from_text`, `_detect_heading`.

**Fix:** preserve DOCX body-element order and native heading/table structure. Record total PDF pages independently of nonempty text, use combined text for document-level fields, and remove positional table duplication where reliable. Carry section state across page boundaries. Model source blocks explicitly, including code fences, language, and original spans. Distinguish blank/scanned/partially extracted pages and report incomplete evidence; OCR is a later capability, not a substitute for these repairs.

### F13 — Embedding size, model version, preprocessing, and retry contracts are incomplete

**P1/P2 · Source-confirmed; quality impact requires evaluation.** The pipeline uses **850 whitespace words**, calls that token count, and does not include heading prefixes in the count. The cross-encoder accepts only 512 model tokens, so large chunks can be represented differently by embedding and reranking. The embedding endpoint response is only lightly validated. The schema dimension is configurable but the baseline migration fixes it at 1024. Search does not require a matching embedding model/version; changing models at the same dimension can silently mix incompatible vector spaces.

`_embed_in_batches()` validates counts, which is good, but a later batch failure causes the outer handler to discard all successful batch results. `_embedding_input()` removes email addresses for documents while query input is unchanged.

Files/functions: [backend/ingestion/pipeline.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/ingestion/pipeline.py) `ingest_document`, `_embed_in_batches`, `_embedding_input`; [backend/ai/ollama_embedding_client.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/ai/ollama_embedding_client.py); [backend/rag/cross_encoder_reranker.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/rag/cross_encoder_reranker.py); [backend/db/models.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/models.py#L295-L334); [backend/alembic/versions/00c7539a7dcd_generate_tables.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/alembic/versions/00c7539a7dcd_generate_tables.py).

**Fix:** use a tokenizer contract per supported model; validate count, dimension, finite components, and usable norm for every vector. Use explicit no-silent-truncation behavior and split overlength inputs. Version model identity/digest, dimension, tokenizer, preprocessing, parser, and chunker; reindex into a new generation before switching. Cache embeddings by that fingerprint plus normalized text hash. Preserve successful work and retry only transient failed batches. Apply deliberate symmetric normalization and retain exact identifiers for lexical matching. Ollama's [embedding API](https://docs.ollama.com/api/embed) accepts batches and defaults to input truncation; explicitly setting and testing this behavior matters.

### F14 — Lexical candidate selection discards relevant chunks before scoring

**P1 · Source-confirmed.** `keyword_search()` builds many `%term%` ILIKE predicates, orders by `chunk_index`, and applies `LIMIT` before Python BM25. A relevant late chunk can be excluded before ranking. `bm25_score_chunks()` computes corpus statistics only from that limited candidate set, then divides by the query-local maximum. Phrases and compound query terms are not represented consistently by its single-token document tokenizer. Generic metadata keys and stored email payloads can enter the searchable blob.

Files/functions: [backend/db/repo/document.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/repo/document.py#L502-L562) `keyword_search`; [backend/rag/stores.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/rag/stores.py) `KeywordSearchStore.search`, `bm25_score_chunks`, `_chunk_tokens`; [backend/services/retrieval_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/retrieval_service.py) `_extract_keyword_terms`.

**Fix:** rank before limiting. A practical first implementation is PostgreSQL weighted `tsvector`/GIN with `websearch_to_tsquery` or explicitly constructed terms, language-aware configuration, and a `simple` channel for identifiers; use trigram/normalized exact matching for filenames where useful. PostgreSQL `ts_rank_cd` is not BM25: label it honestly. A dedicated BM25 engine is optional only if evaluation justifies the operational cost. Search an allowlist of semantic fields, not all JSON/base64. Fuse lexical/vector ranks with RRF and assess quality against the exact same corpus.

### F15 — Document discovery loses documents and bypasses requested filters/scope

**P1 · Source-confirmed.** `DocumentRepository.search_documents()` joins chunks, applies SQL `LIMIT`, and only afterward performs Python `.unique()`. One document with many matching chunks can consume the limit. `DocumentSearchService.search()` accepts `RetrievalFilters` but does not pass `mime_types`. In `ChatService.ask()`, the discovery branch runs before resolving `request.document_ids` and focus locks. Its broad “find/show/list/search/get” classification can answer a factual “list” request with filenames instead of evidence.

Files/functions: [backend/db/repo/document.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/repo/document.py#L182-L234) `search_documents`; [backend/services/document_search_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/document_search_service.py) `search`, `is_document_discovery_query`, `_score_document`; [backend/services/chat_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/chat_service.py#L2290-L2410) `ask`.

**Fix:** resolve hard scope before routing; use it in discovery as well as chunk retrieval. Select distinct document IDs using `EXISTS`, a grouped subquery, or a scored CTE before limiting. Honor MIME and all other filters uniformly. Return matched excerpts from all relevant positions rather than loading all chunks and scoring only the first six. Separate navigation intent from requests to enumerate facts, with explicit completeness limits for “all” or counting questions.

### F16 — Ranking scores have incompatible meanings and a zero-score bug

**P1 · Reproduced for zero fallback and normalization.** `RetrievalCandidate.score` uses truthiness: a legitimate rerank score of `0.0` falls back to the fused score. The probe returned `0.7` for an explicitly zero rerank score. `_normalize_scores()` maps the best member of any nonconstant batch to `0.999`, even scores `[-20, -19]`; a singleton becomes `0.5`. These are relative ranks, not evidence confidence.

`_maybe_true_rerank()` concatenates a cross-encoder head with a heuristic tail, while downstream thresholds compare their scores as if calibrated. `_select_grounded_chunks()` can let filename metadata bypass its minimum and allows a scoped fallback below the usual threshold. Chat then reranks again lexically, potentially undoing the cross-encoder.

Files/functions: [backend/rag/stores.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/rag/stores.py#L17-L39) `RetrievalCandidate.score`; [backend/rag/cross_encoder_reranker.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/rag/cross_encoder_reranker.py) `_normalize_scores`; [backend/rag/retriever.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/rag/retriever.py) `_maybe_true_rerank`; [backend/services/retrieval_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/retrieval_service.py#L355-L468); [backend/ai/rag_postprocess.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/ai/rag_postprocess.py).

**Fix:** use optional score fields and explicit `is not None` precedence. Keep raw cosine distance, lexical rank, fused rank, model relevance, and answer confidence distinct. Use RRF for candidate fusion, one final reranking contract, and a relevance/abstention threshold calibrated on labeled negatives. A sigmoid only applies where the model's output contract calls for it; it does not itself create calibration. Do not force a positive answer from an irrelevant scoped result. Test zero, ties, all-negative, singleton, exact-identifier, and mixed-branch cases.

### F17 — The “support check” can attach citations to unsupported claims

**P1 · Reproduced.** `_answer_is_supported()` does not assess the answer's factual claims; it mostly checks source existence and requested years. `_select_supporting_sources()` explicitly discards `answer`. `_verify_and_normalize_answer()` can therefore append citations to arbitrary text. Given a source saying only “Lunch is served at noon,” the probe accepted “The invoice total is EUR 999999.” and returned it with `[1]`, marked `auto_cited`.

Files/functions: [backend/services/chat_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/chat_service.py#L1881-L1953) `_answer_is_supported`, `_select_supporting_sources`, `_append_citations`; [backend/services/chat_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/chat_service.py#L2091-L2199) `_verify_and_normalize_answer`.

**Fix:** immediately remove blind automatic citation attachment. Validate citation IDs and require claim-to-evidence support. Exact structured values need matching units/currency/entity/date; free-text claims require conservative evidence-span support or a separately evaluated entailment/verification step. If unsupported, repair from evidence or abstain. A citation-format check must not be reported as factual verification. Add contradictory amounts, wrong entity, negation, missing qualifiers, and fabricated-claim fixtures.

### F18 — Source expansion happens after the context budget is enforced

**P1/P2 · Source-confirmed.** `ask()` calls `rerank_and_truncate_sources()` before neighbor, same-document, and summary augmentation. These later stages append full chunks; `build_grounded_prompt()` then includes all of them without a final model-token budget. Early 28,000-character compression therefore does not bound the actual prompt. Synthesized high scores for added chunks can obscure the original retrieval signal.

Files/functions: [backend/services/chat_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/chat_service.py#L2520-L2600) `ask`; [backend/ai/rag_postprocess.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/ai/rag_postprocess.py); [backend/ai/prompt_builder.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/ai/prompt_builder.py) `build_grounded_prompt`; [backend/rag/answer.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/rag/answer.py) `build_source_block`.

**Fix:** retrieve → expand authorized neighbors → deduplicate/rerank → pack once → assign citation IDs → generate. Budget tokens for instructions, history, memory, question, sources, output, and safety margin against the actual generation model. Preserve rows/code fences and evidence spans when excerpting. Carry a ranking reason for neighbors rather than making their scores look model-calibrated. Test long history, large tables, code, many sources, and stable citations after packing.

### F19 — The evaluation harness leaks labels into retrieval and does not evaluate generated answers

**P1 for decision quality · Source-confirmed.** `_run_with_db()` passes `expected_document_ids` as retrieval `document_ids`, restricting the search to gold documents. It labels concatenated retrieved excerpts as the answer; no answer generation is tested. The three checked-in rows have no document IDs. `precision_at_k()` counts repeated document IDs and uses the number returned when fewer than k exist, which can conceal missing results if presented as fixed-k document precision.

Files/functions: [backend/evals/run_offline_eval.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/evals/run_offline_eval.py) `_run_with_db`; [backend/evals/offline_scorer.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/evals/offline_scorer.py) `precision_at_k`, `answer_correctness`, `citation_correctness`; [backend/evals/rag_gold.jsonl](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/evals/rag_gold.jsonl).

**Fix:** keep gold labels entirely out of the query path. Scope only to the case's user/ACL and explicitly requested filters. Use an isolated seeded corpus with distractors. Measure chunk/document Recall@k, fixed-denominator Precision@k, MRR/nDCG, answerable/unanswerable behavior, citation support, actual answer correctness, and latency. Define duplicate handling and metric denominators. Use span/entity/value-aware checks rather than only word containment. Start with representative English/Dutch and other corpus languages, tables, exact IDs, follow-ups, and revoked access; expand the gold set as real failure cases arrive.

### F20 — Clients/models are constructed too often, left unclosed, and cached at the wrong lifetime

**P2 with availability implications · Source-confirmed; impact unmeasured.** API routes instantiate `ChatService` for each request, which creates new LLM and embedding clients. Ingestion constructs clients per document. Their `aclose()` methods are not called by those service owners. `OllamaLLMClient._TTLCache` is per instance, so it normally cannot reuse prior requests. `HybridRetriever` is instantiated inside every `_run_retrieval()`; its lazy cross-encoder cache lasts only that retrieval instance. Model construction itself runs synchronously in the async path.

Files/functions: [backend/api/v1/chat_routes.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/api/v1/chat_routes.py); [backend/services/chat_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/chat_service.py) `__init__`; [backend/services/retrieval_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/retrieval_service.py) `_run_retrieval`; [backend/rag/retriever.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/rag/retriever.py) `_get_true_reranker`; [backend/ai/ollama_llm_client.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/ai/ollama_llm_client.py); [backend/ai/ollama_embedding_client.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/ai/ollama_embedding_client.py); [backend/main.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/main.py) `lifespan`.

**Fix:** own HTTP pools, inference budgets, and bounded caches in API lifespan and separately in each worker process/event loop. Inject lightweight per-request facades. Load a local reranker once per suitable process or use a dedicated inference worker when memory/concurrency measurements justify it. Keep mutable usage metadata request-local; sharing today's `last_usage` field would create a race. Add single-flight cache fill, bounded eviction, metrics, and explicit shutdown. Never share an AsyncClient across forked processes or unrelated loops.

### F21 — Async wrappers still block the event loop; concurrency is only locally bounded

**P2 · Source-confirmed; latency unmeasured.** `parse_document_bytes()` is declared async but runs synchronous PDF/DOCX/ZIP parsing directly. `_celery_worker_is_available()` executes a synchronous broker inspection in an async request path when development fallback checks run. Sync creates a coroutine for every discovered file, even though a semaphore limits active work. Per-instance embedding semaphores do not bound total load across concurrent documents/processes.

Files/functions: [backend/parsers/document_parser.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/parsers/document_parser.py#L103-L141) `parse_document_bytes`; [backend/workers/indexing_tasks.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/workers/indexing_tasks.py) `_celery_worker_is_available`, `should_execute_tasks_locally`; [backend/connectors/nextcloud/sync.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/connectors/nextcloud/sync.py) `snapshot`; [backend/services/nextcloud_sync_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/nextcloud_sync_service.py) `sync_connector`.

**Fix:** move synchronous parsing off the event loop; use bounded threads for blocking I/O and benchmark separate processes/Celery workers for CPU-heavy parsing. A timeout on an await does not stop an already running parser thread, so enforce input/resource limits and use process isolation where cancellation is necessary. Use a bounded producer/consumer queue instead of one task per file. Set worker/provider-wide concurrency limits from database pool and model capacity. Prefer explicit local-worker configuration over broker ping on requests. Keep one SQLAlchemy session per concurrent task, as required by [SQLAlchemy's async session guidance](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-asyncsession-with-concurrent-tasks).

### F22 — ORM overfetching and repeated reads amplify work

**P2 · Source-confirmed structure; benchmark required.** Many relationships use mapper-wide `lazy='selectin'`: `User` loads collections, `Connector` loads documents/jobs, and `Document` loads chunks/insights/tasks. Queries that do not explicitly request those payloads can still trigger eager collection reads. `ChatSessionRepository.list_by_user()` explicitly loads every message while the route returns summaries. Chat augmentation repeatedly calls `list_by_document()` and rebuilds chunk-ID maps. Sync loads connector metadata and checks chunks per item; discovery loads entire document chunk collections.

Files/functions: [backend/db/models.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/models.py) relationships on `User`, `Connector`, `Document`, `ChatSession`; [backend/db/repo/chat.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/repo/chat.py) `list_by_user`; [backend/services/chat_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/chat_service.py#L607-L807) augmentation methods; [backend/services/nextcloud_sync_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/nextcloud_sync_service.py) `_process_item`; [backend/db/repo/document.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/repo/document.py).

**Fix:** use explicit load plans and DTO projections. For collections, consider `lazy='raise'` plus selected eager loads to catch accidental I/O; do not blindly replace everything with lazy loading and create new N+1s. Use authorized batched neighbor queries and request-scoped maps. Batch connector/job/checksum/chunk-health lookups and SQL aggregates. Defer vectors and large JSON unless needed. Instrument actual SQL statements/rows per endpoint before and after; a joined document already exists in normal retrieval, so adding a blanket “fix chunk.document N+1” would misdiagnose that branch.

### F23 — ANN defaults are unsuitable as an unmeasured universal configuration

**P2 · Benchmark required.** The baseline migration creates IVFFlat with 100 lists before initial corpus loading; the repository sets no probes/iterative-scan policy. This can reduce recall, especially with selective ACL/document filters. The exact observed impact depends on corpus size and planner choices; no recall loss percentage is claimed here.

Files: [backend/db/models.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/models.py#L295-L305), [backend/alembic/versions/00c7539a7dcd_generate_tables.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/alembic/versions/00c7539a7dcd_generate_tables.py#L239), [backend/db/repo/document.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/repo/document.py) `semantic_search`.

**Fix:** use exact search for small or highly selective scopes, and benchmark HNSW as the default candidate for a continuously growing corpus. If retaining IVFFlat, build/train after representative data, tune lists/probes, and plan rebuilds. Tune supported iterative scans and compare authorized ANN recall with an exact baseline. Keep visibility inside candidate SQL and use appropriate filter indexes; do not fetch unauthorized neighbors then filter them in Python. [pgvector's documentation](https://github.com/pgvector/pgvector#ivfflat) explains IVFFlat training/probes and [filtered ANN scans](https://github.com/pgvector/pgvector#filtering).

### F24 — Background publication is not coordinated with transaction commit

**P1 · Source-confirmed race.** `_apply_product_intelligence_after_index()` enqueues extraction before the ingestion transaction commits. The worker helper adds a one-second delay, which is not a commit guarantee. New documents can be absent or changed documents can still show the old index. Other enqueue paths commit a job reservation before broker publication, leaving queued records stranded if publication fails. Exceptions after database flush errors are sometimes followed by further writes/commits on the failed session.

Files/functions: [backend/services/indexing_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/indexing_service.py#L153-L174); [backend/workers/indexing_tasks.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/workers/indexing_tasks.py) `enqueue_document_intelligence`; [backend/services/job_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/job_service.py) `reserve_sync_job`; [backend/services/nextcloud_automation_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/nextcloud_automation_service.py) dispatch methods; [backend/services/nextcloud_sync_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/nextcloud_sync_service.py) `_process_item`; [backend/services/email_sync_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/email_sync_service.py) `sync_connector`.

**Fix:** use a transactional outbox for durable work/events, published after commit and retried idempotently. Key work by document/source version and reject stale completions. Use a per-document lease or optimistic generation check so overlapping sync/reindex tasks cannot publish stale versions. Separate long parse/model calls from short publication transactions. On database failures, roll back before recording error state in a fresh transaction. Report “lexical-only”, “unsupported”, “needs OCR”, and per-item failures honestly rather than counting every non-raising ingestion as indexed. Celery's [task documentation](https://docs.celeryq.dev/en/stable/userguide/tasks.html) explicitly calls for idempotent work when using late acknowledgement/redelivery.

### F25 — Worker recovery reuses consumed coroutines; API startup resets healthy workers' jobs

**P1 · Reproduced for coroutine reuse; source-confirmed for job reset.** `_run_in_worker_loop()` catches every `RuntimeError`, closes the loop, and runs the same coroutine again. A coroutine raising a normal business `RuntimeError` was replaced by `cannot reuse already awaited coroutine` in the probe. The engine cache is process-based, so switching loops also risks retaining pooled connections bound to the old loop.

`lifespan()` calls `reset_stale_running_jobs()`, whose query marks **all** running jobs failed without checking age, owner, or heartbeat. Restarting an API process can therefore interfere with live Celery work.

Files/functions: [backend/workers/indexing_tasks.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/workers/indexing_tasks.py#L32-L66); [backend/db/session.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/session.py); [backend/workers/celery_app.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/workers/celery_app.py) worker signals; [backend/main.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/main.py) `lifespan`; [backend/db/repo/sync_job.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/db/repo/sync_job.py) `reset_stale_running_jobs`.

**Fix:** own one persistent event loop/engine/client set per worker process and preserve business exceptions. If recreating work is warranted, use a new coroutine factory after resource cleanup, not an exhausted coroutine. Recover jobs using expiring leases/heartbeats and atomic compare-and-set transitions; API startup must not fail all running jobs. Add tests for business RuntimeError, worker loss, retry/redelivery, cancellation, and API restarts while another worker is healthy.

### F26 — Jobs-page polling can run continuously

**P1 · Source-confirmed; no browser-timer test run.** The jobs `useEffect` depends on the entire `jobs` array, calls `loadJobs()` immediately, and that callback always calls `setJobs(nextJobs)` with a new array. Each completed request changes the effect dependency and triggers another immediate fetch. The in-flight guard only prevents overlap; it does not enforce the desired interval.

File/functions: [frontend/src/workspace/WorkspaceContext.tsx](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/frontend/src/workspace/WorkspaceContext.tsx#L262-L290) `loadJobs`; [frontend/src/workspace/WorkspaceContext.tsx](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/frontend/src/workspace/WorkspaceContext.tsx#L439-L458) jobs polling effect.

**Fix:** separate initial load from polling; depend on stable identity/section and a derived polling interval, or schedule the next timeout only after the current fetch completes. Abort on logout/unmount, pause hidden tabs, and preserve overlap protection. A fake-timer test should prove one initial fetch, bounded interval fetches, and no fetch caused solely by replacing the jobs array. React describes this state/dependency loop in its [effect troubleshooting guide](https://react.dev/reference/react/useEffect#my-effect-keeps-re-running-in-an-infinite-cycle).

### F27 — Overview cache is unbounded and counts are limited to 200 documents

**P2 · Source-confirmed.** `ProductIntelligenceService._overview_cache` is a class dictionary keyed partly by arbitrary search text, with TTL checks but no global eviction. It is not invalidated on ACL/document/task changes. `build_overview()` computes document/task totals from the first 200 visible documents, so counts stop describing the full corpus above that threshold. Cached results can also outlive a permission change until their TTL expires.

File/functions: [backend/services/product_intelligence_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/product_intelligence_service.py) `_overview_cache`, `build_overview` (315–435).

**Fix:** calculate totals with ACL-filtered SQL aggregates; separately paginate detail lists. Use a bounded cache with a complete identity/filter key and content/permission generation, plus explicit invalidation on mutations. Keep cached data authorization-safe and distinguish sampled lists from global totals. Test more than 200 documents, permission revocation, and many distinct search strings.

### F28 — LLM fallback masks provider failures and timeout-specific recovery

**P1/P2 · Source-confirmed.** `OllamaLLMClient.generate()` retries all exceptions and wraps the final one in `RuntimeError`. Chat's `isinstance(exc, httpx.TimeoutException)` recovery cannot see that original timeout. By default `ResilientLLMClient` falls back to a stub, which returns implementation instructions; the permissive verification from F17 can attach citations to it.

Files/functions: [backend/ai/ollama_llm_client.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/ai/ollama_llm_client.py) `generate`; [backend/ai/llm_client.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/ai/llm_client.py) `ResilientLLMClient.generate`, `LLMClientFactory.create`; [backend/services/chat_service.py](https://github.com/oplt/nextcloud_ai/blob/a5ddbc43a3d08fc8aa006132e9184444e845ec28/backend/services/chat_service.py) LLM exception handling in `ask`.

**Fix:** use typed provider errors retaining the cause/retryability and return structured response/usage/fallback metadata. Retry transient network/429/5xx failures with bounded jitter and total deadline, not deterministic validation/4xx errors. Disable stub fallback for normal production requests; return a clearly identified evidence-only degraded response or service error. Verify timeout, malformed output, and provider-unavailable paths.

## Better chunking, embedding, and retrieval design

Retain PostgreSQL and the existing service boundaries initially. The target flow should be:

1. Resolve source version, identity namespace, and effective ACL; download within explicit size/time limits.
2. Extract ordered blocks with original page/character spans, headings, tables, and code regions.
3. Build token-bounded child chunks plus parent/section relationships; record synthetic context separately.
4. Generate/cache validated embeddings under an immutable index fingerprint. Publish one complete generation atomically; keep lexical readiness independent.
5. Resolve the query's hard scope before intent routing. Search lexical and dense branches with identical authorization/filter semantics; allow lexical-only degraded operation.
6. Fuse by rank, rerank one candidate pool, and fetch bounded authorized neighbors/parents. Preserve exact identifiers and diversify redundant evidence with a measured per-document cap or MMR.
7. Pack the final sources once under the generation model's total context budget. Give each packed excerpt a stable citation ID and original provenance.
8. Generate an answer and verify each factual claim against its actual cited evidence; otherwise abstain. Log stage latency and the reason for exclusion/fallback.

Initial tuning ranges are hypotheses, not guaranteed optima: evaluate roughly 250–500 model-token child chunks with 40–80-token overlap, structural exceptions for tables/code, a larger parent section fetched only as needed, approximately 40–80 candidates per retrieval branch, and 20–40 reranker candidates. Compare several settings on the real corpus. A 512-token reranker may require smaller passages or passage-window scoring rather than truncating a large child chunk. Do not blindly change the embedding model, chunk size, or ANN index simultaneously: isolate ablations.

For code-containing documents, keep fenced blocks intact when they fit. For oversized blocks, split at language-aware function/class or statement boundaries where parsers are available, attach symbol/language/section metadata, and preserve indentation, imports needed to understand a snippet, and original line spans. Evaluate lexical symbol/error-code retrieval separately. This is a proposed enhancement, not an existing dedicated code parser.

## Speed, caching, N+1, threads, and asyncio priorities

| Area | Recommended change | Correctness constraint / evidence to collect |
|---|---|---|
| Immediate avoidable load | Fix F26 polling and F20 model/client lifetime first | Request counts, model-load count, connections and memory under repeated requests |
| Embeddings | Persist cache by exact input hash + immutable model/preprocessing/index fingerprint; batch by token/byte budget | Dimension/finite-value checks; bounded cache; no cross-version reuse |
| Query embeddings | Bounded TTL cache plus single-flight for repeated identical queries | Include provider/model/preprocessing and isolation policy; avoid exposing another user's cached text |
| Retrieval results | Add only after version/ACL invalidation exists | Key identity/permission generation, scope, filters, query, corpus version, all ranking settings |
| Generation | Shared bounded cache where useful, returning request-local usage | Include exact packed evidence and versions, model/options/prompt version, and auth boundary; revalidate access before delivery |
| HTTP | Lifespan-owned pools and explicit close; provider-wide semaphores | One process/loop owner; controlled retry budget |
| Database | Explicit load plans, projections, SQL aggregates, batched neighbor reads, rank before LIMIT | Track SQL statements, rows, bytes, and EXPLAIN ANALYZE on representative data |
| Concurrent search | Consider one SQL CTE or independent short-lived sessions for lexical/vector reads | Never `gather()` calls sharing one `AsyncSession`; retain consistent scope/generation |
| Parsing | Bounded executor or worker process; stream/limit large inputs | Threads do not guarantee CPU parallelism or cancellation; choose from measured parser behavior |
| Sync | Producer/consumer queue; batch metadata/health checks; avoid unnecessary downloads; amortize progress writes | Never trade away ACL freshness or infer deletions from partial inventories |
| Indexing | Reuse unchanged chunk embeddings and parse artifacts; atomic generation publication | Content/model/chunker fingerprint and stale-worker detection |
| ANN | Exact baseline, then measured HNSW or trained/tuned IVFFlat | Authorized Recall@k as well as p50/p95 latency and memory |

No percentage speedup is promised: the repository does not contain the production corpus, concurrency distribution, or hardware measurements needed to estimate it honestly.

## Architecture and shorter implementation code

Keep a modular application with separate durable workers. A microservice rewrite would add deployment/consistency work before the current contracts are reliable. A separate inference process is justified only if model memory or concurrency measurements require it.

| Current concentration/duplication | Refactor target | Why |
|---|---|---|
| `ChatService`: 2,725 lines; `ask()`: 525 lines | Small orchestrator over query planning, scoped retrieval, context packing, answer generation, verification, and persistence | One success/failure contract; explicit phase boundaries |
| `ProductIntelligenceService`: 1,402 lines; `_build_tasks()`: 314 lines | Typed extractors/task policies and a task builder, with persistence separate | Avoid repeating task fields, validation, ownership, and webhook logic |
| Filters repeated in document search, chunk search, graph, and expansion | One `RetrievalScope`/filter builder, required by repositories | Prevent ACL/filter drift rather than only reduce lines |
| Candidate ranking in hybrid retriever, service selectors, and chat postprocessor | One rank/score contract and one final ranking/packing step | Preserve model ranking and confidence meaning |
| `_json_text` in stores, reranker, document search | One allowlisted search-field serializer, preferably precomputed | Exclude payload blobs/internal metadata; avoid repeated flattening |
| Two chunk draft types and fallback adapters | One canonical evidence/chunk representation after behavior tests | Reduce field copying while preserving public compatibility |
| Repeated chunk scans and ID-index construction | Batch fetch plus one map per document/request | Move repeated O(n) scans toward O(n + lookups) |
| Nested task/exception branches | Typed `ParseResult`, `EmbeddingResult`, `RetrievalResult`, `GenerationResult`, `IngestionOutcome` | Make degraded versus failed versus successful outcomes explicit |
| Broad commits inside repositories/services | Transaction ownership at application operations, with an outbox | Short transactions and predictable failure recovery |

Proposed new module names, not existing files: `backend/rag/scope.py`, `backend/rag/context_packer.py`, `backend/rag/evidence_verifier.py`, `backend/core/ai_resources.py`, `backend/ingestion/index_versions.py`, and `backend/workers/outbox_dispatcher.py`. Add only boundaries actually used; do not create empty abstractions to meet a directory plan.

Use a registry of named extraction strategies for specialized amount/date/employment handling. Keep fixtures covering each supported behavior before consolidation. Prefer small readable loops and typed results to dense comprehensions or code-golf reductions. Replace repeated membership scans with sets/maps, precompute normalized fields outside loops, and use SQL grouping instead of loading full objects for counts.

## Unused code/files: confirmed references versus removal candidates

Repository-wide reference searches and an AST import scan found the following. “No in-repository caller” does not prove there are no external users, dynamic registrations, or queued Celery task names. The targeted Ruff scan found no unused imports/locals in its selected rules; the issue is mostly unused modules/helpers and duplicated architecture.

| Candidate | Evidence | Action |
|---|---|---|
| `frontend/src/App.css` | No import found; old starter styles | Remove after CSS/build verification |
| `frontend/src/assets/react.svg` | No reference found | Remove |
| `frontend/src/pages/ChatPage.tsx` | No route/import found; current chat is embedded through `ChatWorkspace` | Remove or wire intentionally; no duplicate page needed |
| Root `package-lock.json` | Empty packages object; no root package.json; real frontend lock exists | Remove if no root tooling is introduced |
| `backend/services/conversational_rag_service.py` | Alternate RAG service has no incoming import/caller | Archive/remove after extracting any desired tested behavior; consolidate into the active flow |
| `backend/db/repo/uow.py` | `UnitOfWork` has no caller | Adopt as the real transaction boundary or remove; avoid leaving two competing patterns |
| `backend/connectors/nextcloud/nextcloud_client.py`, `nextcloud_events.py`, `nextcloud_permissions.py`, `nextcloud_sync.py` | Re-export compatibility wrappers with no in-repo consumers | Deprecate only after checking external consumers; their active underlying modules remain |
| `backend/workers/indexing_tasks.py::_run_logged_background_task` | No caller | Remove or use as the sole background runner |
| `backend/db/session.py::run_async_safe` | No caller | Remove if worker runtime consolidation makes it unnecessary |
| `backend/services/product_intelligence_service.py::_classify_document` | No caller; active classification is in `ingestion/classifier.py` | Remove after confirming no intended fallback remains |
| `ChatService._source_evidence_lines`, `ChatService._entity_match_score`; `EvidenceExtractor.field_value_extractor`, `table_row_extractor` | No callers found in snapshot | Remove or integrate only with behavior tests |
| `backend/evals/offline_scorer.py::OfflineEvalRow` | Unused dataclass | Use as a validated evaluation contract or remove |
| `query_writer.is_likely_follow_up`, `build_retrieval_query`; `document_parser.parse_odt_bytes`; `rag_postprocess.compress_sources_for_prompt`; `prompt_builder.available_domain_profiles` | No callers; several look like public compatibility wrappers | Review/deprecate instead of blind deletion |
| `cleanup_stale_connections` | Registered no-op Celery task; no local schedule/call | Keep through a compatibility/drain period if queued/external invocations may exist |

Do **not** label the following unused merely because static calls are absent: FastAPI routes, Pydantic validators, Celery tasks/signals, migrations, CLI scripts, or empty `__init__.py` files. `frontend/public/vite.svg` is still referenced by `frontend/index.html`; replace the branding reference before deleting it. The `ai/chunker.py` adapter and its fallback have callers and are not dead just because a second chunker exists.

## Phased fixing roadmap

| Phase | Work and dependencies | Exit criteria |
|---|---|---|
| **0 — Reproducible baseline** | Pin this snapshot; preserve existing tests; turn audit probes into behavior regressions; repair eval label leakage and seed a small representative corpus | Clean installation; baseline reports identify unsupported measurements; gold IDs never constrain retrieval; CI runs backend/frontend checks |
| **1 — Blockers and containment** | F01–F07, F26; disable blind auto-citation from F17; fix bridge packaging, deployment/extension bootstrap, permissions, webhook defaults, mailbox deletion, polling | Fresh deployment starts; declared reranker mode works; revoked/deleted/unrelated/public-upload-only access is denied; older mail survives bounded sync; jobs poll at intended intervals; unsupported answers are not auto-cited |
| **2 — Index and job consistency** | F08–F10, F24–F25; explicit status model, hash/version separation, transactional outbox, per-document publication control, proper failure transactions | Unchanged sync is metadata-preserving; changed content cannot keep stale chunks; lexical fallback works; retries/redelivery do not duplicate or publish stale work; API restart does not fail a healthy worker's job |
| **3 — Extraction, chunking, embeddings** | F11–F13; ordered structured extraction, token-aware chunks, valid spans, vector validation, cache/fingerprint/generation migration | Budget/coverage/provenance properties hold; table/code tests pass; first/last/blank pages behave correctly; old and new embedding spaces never mix; failed batches are retryable; staged reindex has rollback |
| **4 — Retrieval and grounded answers** | F14–F19; SQL lexical ranking, RRF, calibrated scores, discovery scope, one final context pack, claim verification | Positive and hard-negative gold cases improve or meet baseline; ACL checks stay intact; exact IDs/late chunks found; zero/tie/singleton scores correct; total prompt fits; citations support claims; scoped no-answer cases abstain |
| **5 — Measured performance** | F20–F23, F27–F28; persistent resource owners, bounded work, precise load plans, cache invalidation, accurate overview aggregates, typed provider failures | Agreed workload shows SQL/model loads bounded by relevant work; no unbounded task/cache growth; no permission-stale cache returns; compare p50/p95/p99 latency, throughput, event-loop lag, memory and authorized recall before/after |
| **6 — Consolidation and rollout** | Extract orchestrators/policies, consolidate repeated serializers/filters, remove verified dead code, document operation/migration/recovery | Existing and new behaviors covered; API compatibility reviewed; clean build/lint/tests; fresh-install and upgrade smoke tests; staged reindex verified before promotion; rollback documented |

Implement in small cohesive changes. Do not rewrite the repository or delete the existing index to get a green test. Reindex only after the new pipeline is verified on a staged generation. Maintain a migration/version plan, including which settings require reindexing.

The accompanying `nextcloud_ai_codex_prompt.md` turns this roadmap into a self-contained implementation instruction with concrete targets and tests.
