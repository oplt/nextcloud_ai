# Deployment

Production stack lives in [deployment/docker-compose.yml](/home/polat/Desktop/Projects/NextCloud/deployment/docker-compose.yml:1). It adds:

- Caddy reverse proxy with automatic TLS
- Persistent volumes for Postgres, Redis append-only data, Ollama models, and Caddy state
- Nextcloud + MariaDB with bundled `nc_ai_bridge` (bridge page route is `/workspace` so the app menu resolves under `/apps/nc_ai_bridge/` instead of the bare origin)
- Separate backend, worker, scheduler, and static frontend containers
- Prometheus-compatible metrics at `/metrics` (RAG/chat counters in `backend/core/observability.py`)
- Example alert rules: [prometheus/rules_rag.yml](prometheus/rules_rag.yml)
- Example Grafana PromQL panels: [grafana/RAG_DASHBOARD.md](grafana/RAG_DASHBOARD.md)
- Admin-ready backup and restore scripts under [deployment/scripts](/home/polat/Desktop/Projects/NextCloud/deployment/scripts)

## Required files

1. Copy root deployment env:

   ```bash
   cp .env.example .env
   ```

2. Copy backend app env:

   ```bash
   cp backend/.env.example backend/.env
   ```

3. Set real values:

   - `PUBLIC_HOSTNAME`
   - `ACME_EMAIL`
   - `POSTGRES_PASSWORD`
   - `JWT_SECRET_KEY`
   - `SETTINGS_VAULT_KEY`
   - `NEXTCLOUD_BRIDGE_SHARED_SECRET`
   - `FIRST_SUPERUSER_PASSWORD`

4. For public deployment, keep:

   - `APP_ENV=production`
   - `DEBUG=false`
   - `AUTH_COOKIE_SECURE=true`
   - `CSRF_COOKIE_SECURE=true`
   - `EMBEDDING_PROVIDER=ollama`
   - `LLM_PROVIDER=ollama`

## Start

```bash
make deploy-up
```

Validate rendered compose config:

```bash
make deploy-config
```

Stop stack:

```bash
make deploy-down
```

Create a database backup:

```bash
make deploy-backup-db
```

Restore a backup:

```bash
make deploy-restore-db BACKUP_FILE=deployment/backups/postgres-YYYYMMDD-HHMMSS.sql.gz
```

## Reverse proxy routes

- `/api/*`, `/docs`, `/redoc`, `/openapi.json`, `/health` -> backend
- `/metrics` -> backend
- `/nextcloud*` -> Nextcloud
- all other paths -> static frontend

## Notes

- Caddy issues certificates automatically when `PUBLIC_HOSTNAME` resolves to host.
- Backend/worker/scheduler share `backend/.env`; production overrides in compose force secure cookies and internal service URLs.
- First boot may take longer because Ollama can pull and warm required chat + embedding models.
- Upgrade, webhook registration, bridge auth, and secret rotation runbooks live in [deployment/OPERATIONS.md](/home/polat/Desktop/Projects/NextCloud/deployment/OPERATIONS.md:1).
