include Makefile.local
include Makefile.docker
include Makefile.deploy

.PHONY: help fix check install-hooks commit-ready test-backend-unit test-frontend-unit eval-fixture eval-structure

help:
	@echo ""
	@echo "Local development:"
	@echo "  make local-bootstrap"
	@echo "  make local-install-backend"
	@echo "  make local-install-frontend"
	@echo "  make local-backend"
	@echo "  make local-frontend"
	@echo "  make local-worker"
	@echo "  make local-scheduler"
	@echo "  make local-seed-admin"
	@echo "  make local-dev   (optional: LOCAL_SKIP_NEXTCLOUD=1, NEXTCLOUD_WAIT_SEC=60)"
	@echo "  make local-sync-nc-bridge   (needs NEXTCLOUD_HTML_ROOT= /var/snap/nextcloud/current/nextcloud/extra-apps/)"
	@echo ""
	@echo "Code quality:"
	@echo "  make fix           Auto-fix Python and frontend lint/format issues"
	@echo "  make check         Validate lint, format, and TypeScript without modifying files"
	@echo "  make commit-ready  Run fix, then check"
	@echo "  make install-hooks Install pre-commit hooks"
	@echo "  make test-backend-unit  Offline eval + chat unit tests"
	@echo "  make test-frontend-unit Frontend vitest (jobs poll timers)"
	@echo "  make eval-fixture       Seeded corpus lexical eval (no DB)"
	@echo "  make eval-structure     Gold/fixture load validation"
	@echo ""
	@echo "Docker development:"
	@echo "  make docker-dev   (optional: DOCKER_SKIP_BROWSER=1, DOCKER_WAIT_SEC=180)"
	@echo "  make docker-dev-rebuild"
	@echo "  make docker-migrate"
	@echo "  make docker-up"
	@echo "  make docker-up-detached"
	@echo "  make docker-up-rebuild"
	@echo "  make docker-up-open"
	@echo "  make docker-open-nextcloud"
	@echo "  make docker-nextcloud-up"
	@echo "  make docker-nextcloud-down"
	@echo "  make docker-down"
	@echo "  make docker-build"
	@echo "  make docker-logs"
	@echo "  make docker-ps"
	@echo "  make docker-seed-admin"
	@echo ""
	@echo "Deployment:"
	@echo "  make deploy-config"
	@echo "  make deploy-up"
	@echo "  make deploy-down"
	@echo "  make deploy-logs"
	@echo "  make deploy-seed-admin"
	@echo "  make deploy-backup-db"
	@echo "  make deploy-restore-db BACKUP_FILE=/path/to/backup.sql.gz"

fix:
	ruff check . --fix
	ruff format .
	cd frontend && npx biome check --write .

check:
	ruff check .
	ruff format --check .
	cd frontend && npx biome check .
	cd frontend && npx tsc --noEmit

install-hooks:
	pre-commit install

test-backend-unit:
	cd backend && PYTHONPATH=.. uv run pytest tests/test_offline_scorer.py tests/test_offline_eval_harness.py tests/test_chat_direct_answer.py tests/test_phase1a_deployment.py tests/test_phase1b_auth_webhooks.py tests/test_phase1c_imap_citations.py tests/test_phase2_indexing_jobs.py tests/test_phase3_parse_chunk_embed.py tests/test_phase3_embeddings.py tests/test_phase4_lexical.py tests/test_phase4_score_contract.py tests/test_phase4_context_pack.py tests/test_phase5_resources.py tests/test_phase5_database_async.py tests/test_phase6_simplify.py -q

test-frontend-unit:
	cd frontend && npm test

eval-fixture:
	cd backend && PYTHONPATH=.. uv run python -m backend.evals.run_offline_eval --mode fixture --summary-only

eval-structure:
	cd backend && PYTHONPATH=.. uv run python -m backend.evals.run_offline_eval --mode structure --summary-only

commit-ready: fix check test-backend-unit test-frontend-unit eval-fixture
