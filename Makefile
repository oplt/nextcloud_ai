SHELL := /bin/bash
VENV ?= .venv
PYTEST ?= $(VENV)/bin/pytest
PIP ?= $(VENV)/bin/pip

.PHONY: bootstrap-env install-backend install-frontend dev-up dev-down seed-admin backend-test frontend-build frontend-lint check ci deploy-config deploy-up deploy-down deploy-backup-db deploy-restore-db

bootstrap-env:
	@[ -f .env ] || cp .env.example .env
	@[ -f backend/.env ] || cp backend/.env.example backend/.env
	@[ -f frontend/.env ] || cp frontend/.env.example frontend/.env

install-backend:
	python3.12 -m venv $(VENV)
	$(PIP) install -e "./backend[dev]"

install-frontend:
	npm --prefix frontend ci

dev-up:
	docker compose up --build

dev-down:
	docker compose down

seed-admin:
	docker compose exec backend python -m backend.scripts.seed_admin

backend-test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTEST) -q -p pytest_asyncio.plugin backend/tests

frontend-build:
	npm --prefix frontend run build

frontend-lint:
	npm --prefix frontend run lint

check: backend-test frontend-lint frontend-build

ci: check

deploy-config:
	docker compose --env-file .env -f deployment/docker-compose.yml config >/dev/null

deploy-up:
	docker compose --env-file .env -f deployment/docker-compose.yml up -d --build

deploy-down:
	docker compose --env-file .env -f deployment/docker-compose.yml down

deploy-backup-db:
	bash deployment/scripts/backup_postgres.sh

deploy-restore-db:
	@test -n "$(BACKUP_FILE)" || (echo "Set BACKUP_FILE=/path/to/backup.sql.gz" && exit 1)
	bash deployment/scripts/restore_postgres.sh "$(BACKUP_FILE)"
