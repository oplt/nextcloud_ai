"""Offline rollout contract checks; does not mutate a database or index."""

from __future__ import annotations

import json
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ROUTES = frozenset({"/health", "/api/v1/chat/ask", "/api/v1/documents"})
REQUIRED_TASKS = frozenset(
    {
        "backend.workers.indexing_tasks.dispatch_work_outbox",
        "backend.workers.indexing_tasks.fail_expired_job_leases",
        "backend.workers.indexing_tasks.cleanup_stale_connections",
    }
)


def collect_rollout_contracts() -> dict[str, object]:
    from backend.ai.embedding_contract import active_embedding_fingerprint
    from backend.main import app
    from backend.workers import indexing_tasks  # noqa: F401 - registers tasks
    from backend.workers.celery_app import celery_app

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    heads = list(scripts.get_heads())
    revisions = list(scripts.walk_revisions())
    routes = {route.path for route in app.routes}
    tasks = set(celery_app.tasks)
    fingerprint = active_embedding_fingerprint()
    return {
        "alembic_heads": heads,
        "migration_count": len(revisions),
        "migration_chain_complete": bool(revisions)
        and all(revision.revision for revision in revisions),
        "missing_routes": sorted(REQUIRED_ROUTES - routes),
        "missing_tasks": sorted(REQUIRED_TASKS - tasks),
        "embedding_fingerprint": fingerprint.digest(),
        "embedding_dimension": fingerprint.dimension,
    }


def validate_rollout_contracts() -> dict[str, object]:
    report = collect_rollout_contracts()
    failures: list[str] = []
    if len(report["alembic_heads"]) != 1:
        failures.append("expected exactly one Alembic head")
    if not report["migration_chain_complete"]:
        failures.append("Alembic revision chain is incomplete")
    if report["missing_routes"]:
        failures.append(f"missing routes: {report['missing_routes']}")
    if report["missing_tasks"]:
        failures.append(f"missing Celery tasks: {report['missing_tasks']}")
    if failures:
        raise RuntimeError("; ".join(failures))
    return report


def main() -> None:
    print(json.dumps(validate_rollout_contracts(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
