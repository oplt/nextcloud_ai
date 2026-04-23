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
- Keep `NEXTCLOUD_WEBHOOK_DEBOUNCE_SECONDS` non-zero to suppress event storms.

## Bridge Auth Setup

For the optional Nextcloud bridge app:

1. Set identical `NEXTCLOUD_BRIDGE_SHARED_SECRET` values in the backend and Nextcloud bridge app config.
2. Point the bridge app to the public FastAPI base URL.
3. Keep clocks in sync; the bridge token TTL is short and replay-protected.

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
