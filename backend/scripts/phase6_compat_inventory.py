"""Phase 6: inventory deprecated shims and Celery task drain status.

Scans the repository for remaining references to compatibility re-exports and
the no-op ``cleanup_stale_connections`` task. Does not mutate queues.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"

SHIM_MODULES = (
    "backend.connectors.nextcloud.nextcloud_client",
    "backend.connectors.nextcloud.nextcloud_events",
    "backend.connectors.nextcloud.nextcloud_permissions",
    "backend.connectors.nextcloud.nextcloud_sync",
)
SHIM_PATHS = (
    "connectors/nextcloud/nextcloud_client.py",
    "connectors/nextcloud/nextcloud_events.py",
    "connectors/nextcloud/nextcloud_permissions.py",
    "connectors/nextcloud/nextcloud_sync.py",
)
TASK_NAME = "backend.workers.indexing_tasks.cleanup_stale_connections"
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    "agent-transcripts",
}


def _iter_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix.lower() not in {
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".md",
            ".yml",
            ".yaml",
            ".toml",
            ".json",
            ".txt",
            ".sh",
        }:
            continue
        files.append(path)
    return files


def _find_references(needle: str, *, exclude: set[Path] | None = None) -> list[str]:
    exclude = exclude or set()
    hits: list[str] = []
    pattern = re.compile(re.escape(needle))
    for path in _iter_text_files(REPO_ROOT):
        if path in exclude:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not pattern.search(text):
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        # Ignore self definitions for shim filenames.
        if needle.endswith(".py") and rel.endswith(needle):
            continue
        hits.append(rel)
    return sorted(set(hits))


def inventory() -> dict[str, object]:
    from backend.workers.celery_app import celery_app
    from backend.workers import indexing_tasks  # noqa: F401

    shim_refs: dict[str, list[str]] = {}
    for module, rel_path in zip(SHIM_MODULES, SHIM_PATHS, strict=True):
        shim_rel = f"backend/{rel_path}"
        refs = set(_find_references(module))
        refs.update(_find_references(rel_path))
        refs.discard(shim_rel)
        shim_refs[module] = sorted(refs)

    task_refs = _find_references("cleanup_stale_connections")
    registered = TASK_NAME in set(celery_app.tasks)
    beat = getattr(celery_app.conf, "beat_schedule", {}) or {}
    on_beat = any(
        isinstance(entry, dict) and entry.get("task") == TASK_NAME
        for entry in beat.values()
    )

    runtime_consumers = {
        module: [
            path
            for path in paths
            if path.startswith(("backend/", "frontend/", "nc_ai_bridge/"))
            and "/tests/" not in path
            and not path.endswith("_inventory.py")
            and "phase6_compat" not in path
        ]
        for module, paths in shim_refs.items()
    }
    return {
        "ok": True,
        "shim_modules": shim_refs,
        "in_repo_runtime_consumers": runtime_consumers,
        "cleanup_stale_connections": {
            "task_name": TASK_NAME,
            "registered": registered,
            "on_beat_schedule": on_beat,
            "repo_references": task_refs,
            "status": "retained_noop_compat",
        },
        "recommendation": {
            "remove_shims_now": all(
                len(paths) == 0 for paths in runtime_consumers.values()
            ),
            "remove_cleanup_task_now": False,
            "action": (
                "Safe to remove after one compatibility release once runtime "
                "consumers stay empty, external import inventory is clear, and "
                "Celery queues no longer contain cleanup_stale_connections."
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        report = inventory()
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
