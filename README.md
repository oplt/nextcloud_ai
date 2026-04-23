# NextCloud AI Server

## Overview

This repository contains a private document-search and chat workspace built around Nextcloud content.

The stack has four main parts:

- A FastAPI backend that handles authentication, connector management, document ingestion, chat, health checks, and Nextcloud webhook/bridge endpoints
- A React + Vite frontend for login, chat, connectors, documents, job monitoring, and admin operations
- Celery workers and a beat scheduler for sync and reindex jobs
- An optional Nextcloud app (`nc_ai_bridge/`) that launches the frontend from a logged-in Nextcloud session

At a high level, the system connects to Nextcloud, syncs file metadata and file contents, parses supported document types, stores chunk embeddings in PostgreSQL with `pgvector`, and answers chat questions with grounded source snippets.

## Features

- Local admin sign-in plus Nextcloud bridge sign-in
- Cookie-based session auth with CSRF protection
- Role-based access control for admin, operator, and viewer personas
- Nextcloud connector CRUD, credential testing, sync, and full reindex
- Document ingestion for PDF, DOCX, ODT, TXT, and Markdown files
- ACL-aware document visibility based on Nextcloud owners, users, groups, public links, and superuser access
- Grounded chat responses with saved chat sessions and cited source snippets
- Retrieval controls by connector, file type, path prefix, modified date, and per-chat active document scope
- Document browsing, metadata inspection, inline original-file preview, and per-document reindex
- Background sync/reindex jobs with retry, dead-letter tracking, and document-level failure diagnostics
- Admin UX for user management, role assignment, connector ownership, and audit log browsing
- Nextcloud webhook handling with debounce logic and fallback scheduled syncs
- Health endpoints for liveness, readiness, database, Redis, broker, and Ollama status
- Prometheus-compatible metrics, structured request and trace IDs, and optional Sentry reporting
- Automatic Ollama model readiness checks, model pulling, and warm-up when Ollama providers are enabled

## Tech Stack

### Backend

- Python 3.12
- FastAPI
- SQLAlchemy + Alembic
- PostgreSQL + `pgvector`
- Celery + Redis
- Ollama
- `pdfplumber` and `python-docx`
- `prometheus-client` and `sentry-sdk`

### Frontend

- React 19
- TypeScript
- Vite
- Material UI
- Tailwind CSS

### Integration

- Nextcloud WebDAV + OCS APIs
- Optional Nextcloud app bridge compatible with Nextcloud 31-32

## Architecture / Folder Structure

```text
.
├── .env.example          # Deployment-level reverse proxy variables
├── Makefile              # Bootstrap, validate, dev, and deploy commands
├── backend/
│   ├── ai/                 # Embeddings, LLM clients, prompt building, citations, Ollama runtime
│   ├── alembic/            # Database migrations
│   ├── api/                # FastAPI routers, auth helpers, dependencies
│   ├── connectors/nextcloud/ # Nextcloud client, bridge token handling, permissions, webhooks
│   ├── core/               # Settings, security, CSRF, exceptions
│   ├── db/                 # Models, repositories, sessions
│   ├── ingestion/          # Chunking and embedding pipeline
│   ├── parsers/            # PDF, DOCX, ODT, TXT, Markdown parsing
│   ├── scripts/            # Admin seeding script
│   ├── services/           # Auth, chat, retrieval, connector sync, health, jobs
│   ├── tests/              # Pytest suite
│   ├── workers/            # Celery app and background tasks
│   ├── Dockerfile
│   ├── .env.example
│   └── pyproject.toml
├── deployment/             # TLS-ready compose stack, backups, upgrade and rotation runbooks
├── frontend/
│   ├── src/
│   │   ├── api/           # Frontend API client
│   │   ├── components/    # Chat, connector, document, and job UI
│   │   ├── hooks/         # Session hook
│   │   └── pages/         # Login, overview, connectors, documents, jobs, admin
│   ├── Dockerfile
│   ├── .env.example
│   └── package.json
├── nc_ai_bridge/           # Optional Nextcloud app for SSO-style handoff
└── docker-compose.yml      # Full local stack
```

## Setup and Installation

### Option A: Full stack with Docker Compose

Prerequisite: Docker with Compose.

From the repository root:

```bash
make bootstrap-env
make dev-up
```

This starts:

- PostgreSQL on `localhost:5432`
- Redis on `localhost:6379`
- Ollama on `localhost:11434`
- FastAPI backend on `localhost:8000`
- React frontend on `localhost:5173`
- A Celery worker
- A Celery beat scheduler

Seed the first admin account after the backend is up:

```bash
docker compose exec backend python -m backend.scripts.seed_admin
```

### Option B: Run services locally

#### Backend install

Prerequisites:

- Python 3.12
- PostgreSQL with the `vector` extension available
- Redis
- Ollama. In `backend/.env.example`, both `EMBEDDING_PROVIDER` and `LLM_PROVIDER` are set to `ollama`.

Create a virtual environment and install the backend:

```bash
make bootstrap-env
make install-backend
```

#### Frontend install

Prerequisite: Node.js with npm.

```bash
make install-frontend
```

## Configuration

Bootstrap env files from examples:

```bash
make bootstrap-env
```

### `backend/.env`

Start from `backend/.env.example`, then set:

- Application: `APP_NAME`, `APP_ENV`, `DEBUG`, `API_V1_PREFIX`, `FRONTEND_URL`
- Database and queue: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`, `DATABASE_URL`, `REDIS_URL`, `REDIS_PORT`, `CELERY_TASK_ALWAYS_EAGER`
- Auth and admin bootstrap: `JWT_SECRET_KEY`, `SETTINGS_VAULT_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `AUTH_ISSUER`, `AUTH_AUDIENCE`, `AUTH_COOKIE_NAME`, `AUTH_COOKIE_SECURE`, `AUTH_COOKIE_SAMESITE`, `AUTH_COOKIE_DOMAIN`, `FIRST_SUPERUSER_EMAIL`, `FIRST_SUPERUSER_PASSWORD`
- AI runtime: `EMBEDDING_DIM`, `EMBEDDING_PROVIDER`, `LLM_PROVIDER`, `OLLAMA_BASE_URL`, `OLLAMA_EMBEDDING_MODEL`, `OLLAMA_CHAT_MODEL`, `OLLAMA_PORT`
- Nextcloud integration: `NEXTCLOUD_BRIDGE_SHARED_SECRET`, `NEXTCLOUD_BRIDGE_ISSUER`, `NEXTCLOUD_BRIDGE_AUDIENCE`, `NEXTCLOUD_BRIDGE_TTL_SECONDS`, `NEXTCLOUD_BRIDGE_ALLOWED_CLOCK_SKEW_SECONDS`, `NEXTCLOUD_BRIDGE_REDIS_URL`, `NEXTCLOUD_WEBHOOK_SECRET`, `NEXTCLOUD_VERIFY_TLS`, `NEXTCLOUD_REQUEST_TIMEOUT_SECONDS`
- Observability: `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE`, `METRICS_ENABLED`, `METRICS_PATH`, `REQUEST_ID_HEADER_NAME`, `TRACE_ID_HEADER_NAME`
- Frontend API base value also appears in this file: `VITE_API_BASE_URL`

Additional optional settings with code defaults live in `backend/core/config.py`.

### `frontend/.env`

Start from `frontend/.env.example`. It includes:

- `VITE_API_BASE_URL`

### Root `.env`

Start from `.env.example` when using [deployment/docker-compose.yml](/home/polat/Desktop/Projects/NextCloud/deployment/docker-compose.yml:1). It includes:

- `PUBLIC_HOSTNAME`
- `ACME_EMAIL`
- `FRONTEND_API_BASE_URL`

### What still needs manual input

- Replace example secrets and passwords in `backend/.env` before any non-local deployment.
- Supply real Nextcloud connector values in the UI or API: base URL, username, app password, and root path.
- `NEXTCLOUD_WEBHOOK_SECRET` is blank in `backend/.env`; set it if you want signed webhook verification on `/api/v1/nextcloud/webhooks`.
- `NEXTCLOUD_BRIDGE_REDIS_URL` is blank in `backend/.env`; set it if you want separate Redis-backed replay protection for bridge tokens.
- Update `FRONTEND_URL` and `VITE_API_BASE_URL` if you are not running on `localhost:5173` and `localhost:8000`.
- If you install the Nextcloud app bridge, you must also set Nextcloud app config values such as `fastapi_base_url` and keep `overwrite.cli.url` correct in the Nextcloud server config.
- This repository does not include a root `LICENSE` file, so repository-wide licensing still needs to be clarified.

## Run Instructions

### Backend

Apply database migrations:

```bash
source .venv/bin/activate
alembic -c backend/alembic.ini upgrade head
```

Start the API server:

```bash
source .venv/bin/activate
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Seed the first local admin user:

```bash
source .venv/bin/activate
python -m backend.scripts.seed_admin
```

Start the Celery worker:

```bash
source .venv/bin/activate
celery -A backend.workers.celery_app.celery_app worker --loglevel=INFO
```

Start the Celery beat scheduler:

```bash
source .venv/bin/activate
celery -A backend.workers.celery_app.celery_app beat --loglevel=INFO
```

Notes:

- In development, connector sync and document reindex requests can fall back to local execution if no Celery worker is detected.
- Scheduled fallback connector syncs come from Celery beat, so the scheduler is still needed for that behavior.

### Frontend

Start the development server:

```bash
npm --prefix frontend run dev -- --host 0.0.0.0
```

### Makefile shortcuts

```bash
make backend-test
make frontend-lint
make frontend-build
make check
make ci
make seed-admin
```

`make backend-test` disables unrelated host pytest plugins and loads `pytest_asyncio` explicitly, which avoids false failures from globally installed plugins.
`make ci` runs backend tests plus frontend lint and build in one command.

Create a production build:

```bash
npm --prefix frontend run build
```

Preview the production build:

```bash
npm --prefix frontend run preview
```

## Usage Examples

### 1. First login

1. Start the stack.
2. Run `python -m backend.scripts.seed_admin` or `docker compose exec backend python -m backend.scripts.seed_admin`.
3. Open `http://localhost:5173`.
4. Sign in with `FIRST_SUPERUSER_EMAIL` and `FIRST_SUPERUSER_PASSWORD` from `backend/.env`.

### 2. Add a Nextcloud connector

In the frontend Connectors page, fill in:

- Display name
- Base URL
- Username
- App password
- Root path
- TLS verification choice

Then use:

- `Test` to verify credentials
- `Sync` to sync and index changed files
- `Full reindex` to force reprocessing

### 3. Browse synced documents

After a sync completes:

1. Open the Documents page.
2. Select a document from the table.
3. Review metadata, access lists, parse status, and preview the original file.
4. Use `Reindex` if you want to re-run parsing and embedding for that document.

### 4. Ask grounded questions

Use the Overview page chat workspace to ask questions against indexed content.

The backend stores chat sessions and returns:

- The assistant answer
- Source snippets
- Cited sources
- Active context document IDs and document metadata

### 5. Health checks

Unauthenticated health endpoints:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/ready
```

### 6. Optional Nextcloud bridge app

Install the bridge app into Nextcloud by copying `nc_ai_bridge/` into `custom_apps/`, then enable it:

```bash
sudo -u www-data php occ app:enable nc_ai_bridge
```

Configure the app values:

```bash
sudo -u www-data php occ config:app:set nc_ai_bridge fastapi_base_url --value="<your-fastapi-base-url>"
sudo -u www-data php occ config:app:set nc_ai_bridge bridge_shared_secret --value="<same-value-as-NEXTCLOUD_BRIDGE_SHARED_SECRET>"
sudo -u www-data php occ config:app:set nc_ai_bridge bridge_issuer --value="nextcloud-bridge"
sudo -u www-data php occ config:app:set nc_ai_bridge bridge_audience --value="fastapi-nextcloud"
sudo -u www-data php occ config:app:set nc_ai_bridge bridge_ttl_seconds --value="60"
```

Also make sure the Nextcloud server has a correct canonical base URL in `config/config.php`:

```php
'overwrite.cli.url' => '<your-nextcloud-base-url>',
```

When a user opens the `AI Workspace` navigation entry in Nextcloud, the app:

1. Calls the bridge bootstrap endpoint inside Nextcloud
2. Gets a short-lived signed bridge token
3. Posts that token to `/api/v1/auth/nextcloud/sso/consume`
4. Receives backend session cookies and is redirected to the frontend

## Deployment

Production deployment package now lives in [deployment/README.md](/home/polat/Desktop/Projects/NextCloud/deployment/README.md:1).

Quick start:

```bash
cp .env.example .env
cp backend/.env.example backend/.env
make deploy-config
make deploy-up
```

What it adds:

- Caddy reverse proxy with automatic TLS
- Persistent Postgres, Redis, Ollama, and Caddy volumes
- Static production frontend container
- Dedicated backend worker and scheduler services
- Prometheus-compatible `/metrics`
- Backup and restore scripts in `deployment/scripts`
- Upgrade, webhook, bridge auth, and credential rotation runbooks in `deployment/OPERATIONS.md`

## Troubleshooting

- `GET /api/v1/health/ready` returns `503`: the response body includes separate readiness details for the database, Redis, broker, and Ollama runtime.
- Nextcloud connector test fails with authentication errors: the backend expects a Nextcloud username and app password, not a normal browser password.
- Nextcloud connector cannot reach the server: the backend raises a message that includes the base URL and the upstream request error.
- Documents are not indexed: only PDF, DOCX, ODT, TXT, and Markdown parsing is implemented in `backend/parsers/document_parser.py`.
- Ollama startup is slow on first run: the backend and worker warm required models and will pull missing models automatically when Ollama providers are enabled.
- The Nextcloud bridge page says configuration is incomplete: set `nc_ai_bridge.fastapi_base_url` in the Nextcloud app config.
- The Nextcloud bridge bootstrap fails because base URL is missing: set `overwrite.cli.url` in Nextcloud.

## Contribution

This repository does not include a dedicated contribution guide.

Useful checks that are present in the repo:

```bash
make backend-test
make frontend-build
```

There is a backend pytest suite in `backend/tests/`. No frontend test runner is configured in this repository.

## License

No root `LICENSE` file is present in this repository.

The only explicit license declaration in the codebase is inside `nc_ai_bridge/composer.json`, which declares `AGPL-3.0-or-later` for the Nextcloud bridge package. That does not establish a repository-wide license by itself.
