# Nextcloud AI Server

This project is a separate application that integrates with Nextcloud. 
It is not a native Nextcloud app inside the Nextcloud `apps/` folder.

It provides:

- a FastAPI backend
- a React frontend
- PostgreSQL with `pgvector`
- Redis + Celery workers for sync and reindex jobs
- a Nextcloud connector that imports files through WebDAV/OCS
- optional Nextcloud bridge SSO and webhook endpoints

## 1. Architecture

The flow is:

1. A local admin or a bridged Nextcloud user signs in.
2. You create a Nextcloud connector with a base URL, username, app password, and root path.
3. A sync job crawls Nextcloud, reads ACL/share information, downloads changed files, parses them, chunks them, and stores embeddings in PostgreSQL.
4. The chat flow retrieves visible chunks only and answers with grounded sources.

Main URLs:

- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000`
- API prefix: `http://localhost:8000/api/v1`
- Health check: `http://localhost:8000/health`

## 2. Prerequisites

Minimum:

- Docker and Docker Compose
- a working Nextcloud instance
- a Nextcloud user account for the connector
- a Nextcloud app password for that account

Recommended for local development without Docker:

- Python 3.12
- Node.js 20+
- PostgreSQL 16 with the `vector` extension
- Redis 7+

## 3. Prepare Nextcloud

Before you start this app, prepare the Nextcloud side:

1. Log in to Nextcloud.
2. Create an app password for the account that this integration will use.
3. Decide which folder should be indexed.
4. Note the base URL of your Nextcloud instance.

Example connector values:

- Base URL: `https://cloud.example.com`
- Username: `service-account`
- App password: generated in Nextcloud security settings
- Root path: `/Documents/Knowledge`

Notes:

- Use an app password, not the normal login password.
- `root_path` must exist in the connector user’s Nextcloud files.
- If your Nextcloud uses a private CA in development, set `verify_tls` to `false` only for that environment.

## 4. Quick Start With Docker

This is the recommended setup from zero.

### 4.1 Create the backend env file

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and change at least:

- `JWT_SECRET_KEY`
- `SETTINGS_VAULT_KEY`
- `FIRST_SUPERUSER_EMAIL`
- `FIRST_SUPERUSER_PASSWORD`
- `FRONTEND_URL`
- `VITE_API_BASE_URL`

If you want Ollama-backed chat and embeddings, also change:

- `LLM_PROVIDER=ollama`
- `EMBEDDING_PROVIDER=ollama`

### 4.2 Start the full stack

```bash
docker compose up --build
```

What starts:

- `postgres`
- `redis`
- `ollama`
- `backend`
- `worker`
- `frontend`

The backend container runs `alembic upgrade head` automatically on start.

### 4.3 Create the first admin user

Open another terminal:

```bash
docker compose exec backend python -m backend.scripts.seed_admin
```

Expected result:

- `Admin created`
- or `Admin already exists`

### 4.4 Optional: pull Ollama models

Only needed if you use `ollama` providers.

```bash
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull llama3:8b-instruct
```

### 4.5 Log in

Open:

- `http://localhost:5173`

Use the admin credentials from `backend/.env`.

## 5. Create the Nextcloud Connector

After login:

1. Open the `Connectors` page.
2. Create a new connector.
3. Fill:
   - `display_name`
   - `base_url`
   - `username`
   - `secret` = Nextcloud app password
   - `root_path`
   - `verify_tls`
4. Click `Save Connector`.
5. Click `Test`.
6. Click `Sync` or `Full Reindex`.

What happens on sync:

- folders are crawled recursively
- file metadata is read from WebDAV
- access rules are built from Nextcloud sharing data
- changed files are downloaded
- supported files are parsed and indexed
- deleted/missing files are marked deleted

Supported file types in the current codebase:

- `.pdf`
- `.docx`
- `.txt`
- `.md`
- `.markdown`

## 6. Local Development Without Docker

### 6.1 Backend

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ./backend[dev]
cp backend/.env.example backend/.env
```

Create PostgreSQL and enable `vector`:

```sql
CREATE DATABASE nextcloud_ai;
\c nextcloud_ai
CREATE EXTENSION IF NOT EXISTS vector;
```

Run migrations:

```bash
alembic -c backend/alembic.ini upgrade head
```

Seed the admin:

```bash
python -m backend.scripts.seed_admin
```

Run the backend:

```bash
uvicorn backend.main:app --reload --port 8000
```

Run the worker:

```bash
celery -A backend.workers.celery_app.celery_app worker --loglevel=INFO
```

In `APP_ENV=development`, connector sync and document reindex run eagerly in the backend process by default. A separate worker is only required if you explicitly set `CELERY_TASK_ALWAYS_EAGER=false` or when running non-development environments.

### 6.2 Frontend

```bash
cd frontend
npm install
npm run dev
```

## 7. API Endpoints You Will Use

Core auth:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Connector flow:

- `POST /api/v1/connectors`
- `GET /api/v1/connectors`
- `POST /api/v1/connectors/{connector_id}/test`
- `POST /api/v1/connectors/{connector_id}/sync`

Documents and jobs:

- `GET /api/v1/documents`
- `GET /api/v1/documents/{document_id}`
- `POST /api/v1/documents/{document_id}/reindex`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`

Chat:

- `POST /api/v1/chat/ask`
- `GET /api/v1/chat/sessions`
- `GET /api/v1/chat/sessions/{session_id}`

## 8. Advanced Nextcloud SSO Bridge

This repo already includes a bridge-token flow for Nextcloud-driven login.

Relevant env vars:

- `NEXTCLOUD_BRIDGE_SHARED_SECRET`
- `NEXTCLOUD_BRIDGE_ISSUER`
- `NEXTCLOUD_BRIDGE_AUDIENCE`
- `NEXTCLOUD_BRIDGE_TTL_SECONDS`
- `NEXTCLOUD_BRIDGE_ALLOWED_CLOCK_SKEW_SECONDS`
- `NEXTCLOUD_BRIDGE_REDIS_URL`

Backend endpoints:

- `POST /api/v1/auth/nextcloud/exchange`
- `POST /api/v1/auth/nextcloud/sso/consume`

Expected bridge token claims:

- `iss`
- `aud`
- `sub`
- `preferred_username`
- `display_name`
- `email`
- `groups`
- `nc_base_url`
- `jti`
- `iat`
- `nbf`
- `exp`

Recommended bridge setup:

1. Use the same `NEXTCLOUD_BRIDGE_SHARED_SECRET` in Nextcloud and this backend.
2. Set `NEXTCLOUD_BRIDGE_REDIS_URL` so tokens are single-use.
3. Redirect the user from Nextcloud to `POST /api/v1/auth/nextcloud/sso/consume` with `bridge_token`.
4. Let the backend set the auth cookie and redirect to the frontend.

If Redis is not configured for the bridge, replay protection is disabled.

## 9. Advanced Webhook Integration

This repo exposes:

- `POST /api/v1/nextcloud/webhooks`

Optional env var:

- `NEXTCLOUD_WEBHOOK_SECRET`

If `NEXTCLOUD_WEBHOOK_SECRET` is set, send:

- header `X-Webhook-Signature`
- value = `HMAC_SHA256(raw_body, NEXTCLOUD_WEBHOOK_SECRET)`

Current behavior:

- the endpoint validates the signature
- accepts JSON payloads
- normalizes the payload into a webhook event response

It does not yet schedule a sync automatically. If you want near-real-time updates, wire the webhook sender in Nextcloud and then extend this endpoint to enqueue connector sync jobs.

## 10. Security Notes

- Change all default secrets before exposing the app.
- Keep `SETTINGS_VAULT_KEY` stable. It is used to decrypt stored connector secrets.
- Use `AUTH_COOKIE_SECURE=true` behind HTTPS.
- Prefer `AUTH_COOKIE_SAMESITE=lax` unless you have a cross-site requirement.
- Keep `NEXTCLOUD_VERIFY_TLS=true` in production.
- Use a dedicated Nextcloud service account if you are indexing shared company folders.

## 11. Production Checklist

- Put the frontend and backend behind HTTPS.
- Use a real domain for `FRONTEND_URL`.
- Set strong secrets in `backend/.env`.
- Use managed PostgreSQL or persistent volumes.
- Keep Redis persistent enough for job and bridge behavior.
- Enable Ollama only if your host has enough CPU/GPU and RAM.
- Put the worker in a separate process/container in production.
- Monitor failed sync jobs in `/api/v1/jobs`.

## 12. Troubleshooting

### Connector test fails

Check:

- base URL is correct
- username is correct
- app password is correct
- TLS verification matches your certificate setup

### Login works but connector sync finds nothing

Check:

- `root_path` exists
- the connector account can access that folder
- the folder is inside the connector account’s Nextcloud files tree

### Chat has no useful answers

Check:

- documents were actually indexed
- the worker is running if `CELERY_TASK_ALWAYS_EAGER=false` or you are outside development
- file types are supported
- embeddings are configured correctly
- the logged-in user is allowed to see the synced documents

### Restart broke connector decryption

That usually means `SETTINGS_VAULT_KEY` or `JWT_SECRET_KEY` changed after connectors were saved. Restore the original key or recreate the connectors.

## 13. Tests

Backend tests:

```bash
. .venv/bin/activate
cd backend
pytest -q
```

## 14. Current Important Limitation

The project integrates with Nextcloud over APIs and optional bridge endpoints. If you need a native Nextcloud app with PHP controllers, app registration, admin settings pages, and in-platform UI, that is a different architecture and is not what this repository currently contains.
