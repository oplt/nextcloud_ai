include Makefile.local
-include Makefile.docker
include Makefile.deploy

.PHONY: help fix check install-hooks commit-ready test-backend-unit test-frontend-unit eval-fixture eval-structure eval-db eval-chunk-grid benchmark-fixture phase1-smoke phase1-docker-smoke phase1-rerank-smoke phase1-imap-smoke phase1-bridge-smoke phase1-nc-acl-smoke phase2-smoke phase2-outbox-smoke phase2-migrate-smoke phase3-smoke phase3-chunk-properties phase3-reindex-smoke phase3-embed-smoke phase4-smoke phase4-quality-compare phase4-threshold-calibrate phase4-injection-test phase5-smoke phase5-db-benchmark phase5-ann-benchmark phase5-concurrency-smoke phase6-smoke phase6-compat-inventory phase6-frontend-build phase6-rollout-rehearsal

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
	@echo "  make eval-db            Rollback-only DB retrieval eval (local test DB only)"
	@echo "  make eval-chunk-grid    Compare supported chunk size/overlap settings"
	@echo "  make benchmark-fixture  Measure repeatable offline RAG latency/resources"
	@echo "  make phase1-smoke       Full Phase 1 integration smokes (Docker + real rerank + IMAP)"
	@echo "  make phase1-docker-smoke  Build/run API worker beat migrate seed ready"
	@echo "  make phase1-rerank-smoke  Real CrossEncoder relevance smoke"
	@echo "  make phase1-imap-smoke    Disposable GreenMail IMAP smoke"
	@echo "  make phase1-bridge-smoke  Docker Nextcloud bridge install/routes"
	@echo "  make phase1-nc-acl-smoke  Live OCS grant/inheritance smoke"
	@echo "  make phase2-smoke         Outbox/lease + migration upgrade smokes"
	@echo "  make phase2-outbox-smoke  Real PG outbox redelivery + generation race + leases"
	@echo "  make phase2-migrate-smoke Fresh install + prior-revision upgrade"
	@echo "  make phase3-smoke         Chunk properties + reindex + live embed smokes"
	@echo "  make phase3-chunk-properties  Hypothesis chunk invariants"
	@echo "  make phase3-reindex-smoke Staged promote/rollback on disposable PG"
	@echo "  make phase3-embed-smoke   Live Ollama truncate=false / dim / split-pool"
	@echo "  make phase4-smoke         Quality compare + threshold calibrate + injection tests"
	@echo "  make phase4-quality-compare  Fixture baseline vs DB final metrics"
	@echo "  make phase4-threshold-calibrate  Held-out hard-neg floor sweep"
	@echo "  make phase4-injection-test Prompt-injection / ACL authority tests"
	@echo "  make phase5-smoke         DB workload + ANN + concurrency smokes"
	@echo "  make phase5-db-benchmark  DB retrieval p50/p95/p99 + lag/SQL/cache"
	@echo "  make phase5-ann-benchmark Exact vs IVFFlat vs HNSW recall/latency"
	@echo "  make phase5-concurrency-smoke Concurrent retrieve/parse/embed/cache"
	@echo "  make phase6-smoke         Compat inventory + frontend build + rollout rehearsal"
	@echo "  make phase6-compat-inventory  Deprecated shim/task consumer inventory"
	@echo "  make phase6-frontend-build Production Vite build"
	@echo "  make phase6-rollout-rehearsal Local rollout checklist rehearsal"
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
	cd frontend && npm run lint -- --fix

check:
	ruff check .
	ruff format --check .
	cd frontend && npm run lint
	cd frontend && npx tsc --noEmit

install-hooks:
	pre-commit install

test-backend-unit:
	cd backend && PYTHONPATH=.. uv run pytest tests/test_offline_scorer.py tests/test_offline_eval_harness.py tests/test_chat_direct_answer.py tests/test_phase1a_deployment.py tests/test_phase1b_auth_webhooks.py tests/test_phase1c_imap_citations.py tests/test_phase2_indexing_jobs.py tests/test_phase3_parse_chunk_embed.py tests/test_phase3_chunk_properties.py tests/test_phase3_embeddings.py tests/test_phase4_lexical.py tests/test_phase4_score_contract.py tests/test_phase4_context_pack.py tests/test_phase4_prompt_injection.py tests/test_phase4_threshold_calibrate.py tests/test_phase5_resources.py tests/test_phase5_database_async.py tests/test_phase5_ann_benchmark.py tests/test_phase6_simplify.py -q

test-frontend-unit:
	cd frontend && npm test

eval-fixture:
	cd backend && PYTHONPATH=.. uv run python -m backend.evals.run_offline_eval --mode fixture --summary-only

eval-structure:
	cd backend && PYTHONPATH=.. uv run python -m backend.evals.run_offline_eval --mode structure --summary-only

eval-db:
	cd backend && PYTHONPATH=.. uv run python -m backend.evals.run_offline_eval --mode retrieval --seed-db --summary-only

eval-chunk-grid:
	cd backend && PYTHONPATH=.. uv run python -m backend.evals.chunk_grid

benchmark-fixture:
	cd backend && PYTHONPATH=.. uv run python -m backend.evals.performance_benchmark

phase1-docker-smoke:
	chmod +x deployment/scripts/phase1_docker_smoke.sh
	bash deployment/scripts/phase1_docker_smoke.sh

phase1-rerank-smoke:
	cd backend && PYTHONPATH=.. .venv/bin/python -m backend.scripts.phase1_rerank_smoke --force

phase1-imap-smoke:
	cd backend && PYTHONPATH=.. .venv/bin/python -m backend.scripts.phase1_imap_smoke

phase1-bridge-smoke:
	chmod +x deployment/scripts/phase1_bridge_smoke.sh
	PHASE1_KEEP_STACK=$${PHASE1_KEEP_STACK:-0} bash deployment/scripts/phase1_bridge_smoke.sh

phase1-nc-acl-smoke:
	chmod +x deployment/scripts/phase1_nc_acl_smoke.sh
	PHASE1_KEEP_STACK=$${PHASE1_KEEP_STACK:-0} bash deployment/scripts/phase1_nc_acl_smoke.sh

phase1-smoke: phase1-rerank-smoke phase1-imap-smoke phase1-docker-smoke phase1-bridge-smoke phase1-nc-acl-smoke

phase2-outbox-smoke:
	chmod +x deployment/scripts/phase2_outbox_smoke.sh deployment/scripts/phase2_infra.sh
	bash deployment/scripts/phase2_outbox_smoke.sh

phase2-migrate-smoke:
	chmod +x deployment/scripts/phase2_migrate_smoke.sh deployment/scripts/phase2_infra.sh
	bash deployment/scripts/phase2_migrate_smoke.sh

phase2-smoke: phase2-outbox-smoke phase2-migrate-smoke

phase3-chunk-properties:
	cd backend && PYTHONPATH=.. .venv/bin/pytest tests/test_phase3_chunk_properties.py -q

phase3-reindex-smoke:
	chmod +x deployment/scripts/phase3_reindex_smoke.sh
	bash deployment/scripts/phase3_reindex_smoke.sh

phase3-embed-smoke:
	chmod +x deployment/scripts/phase3_embed_smoke.sh
	bash deployment/scripts/phase3_embed_smoke.sh

phase3-smoke: phase3-chunk-properties phase3-reindex-smoke phase3-embed-smoke

phase4-quality-compare:
	chmod +x deployment/scripts/phase4_quality_compare.sh
	bash deployment/scripts/phase4_quality_compare.sh

phase4-threshold-calibrate:
	chmod +x deployment/scripts/phase4_threshold_calibrate.sh
	bash deployment/scripts/phase4_threshold_calibrate.sh

phase4-injection-test:
	cd backend && PYTHONPATH=.. .venv/bin/pytest tests/test_phase4_prompt_injection.py -q

phase4-smoke: phase4-threshold-calibrate phase4-injection-test phase4-quality-compare

phase5-db-benchmark:
	chmod +x deployment/scripts/phase5_db_benchmark.sh
	bash deployment/scripts/phase5_db_benchmark.sh

phase5-ann-benchmark:
	chmod +x deployment/scripts/phase5_ann_benchmark.sh
	bash deployment/scripts/phase5_ann_benchmark.sh

phase5-concurrency-smoke:
	chmod +x deployment/scripts/phase5_concurrency_smoke.sh
	bash deployment/scripts/phase5_concurrency_smoke.sh

phase5-smoke: phase5-db-benchmark phase5-ann-benchmark phase5-concurrency-smoke

phase6-compat-inventory:
	cd backend && PYTHONPATH=.. .venv/bin/python -m backend.scripts.phase6_compat_inventory

phase6-frontend-build:
	cd frontend && npm ci && npm run build

phase6-rollout-rehearsal:
	chmod +x deployment/scripts/phase6_rollout_rehearsal.sh
	bash deployment/scripts/phase6_rollout_rehearsal.sh

phase6-smoke: phase6-compat-inventory phase6-frontend-build phase6-rollout-rehearsal

commit-ready: fix check test-backend-unit test-frontend-unit eval-fixture
