"""Session-scoped structured memory (TTL, goals, locks) separate from document retrieval."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


def empty_memory() -> dict[str, Any]:
    return {
        "version": 1,
        "session_summary": None,
        "long_term_items": [],
        "focus_lock_document_ids": [],
    }


def normalize_memory(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = empty_memory()
    if not raw:
        return base
    for key in ("session_summary", "long_term_items", "focus_lock_document_ids", "version"):
        if key in raw:
            base[key] = raw[key]
    if not isinstance(base["long_term_items"], list):
        base["long_term_items"] = []
    if not isinstance(base["focus_lock_document_ids"], list):
        base["focus_lock_document_ids"] = []
    return base


def prune_expired_items(memory: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    items = memory.get("long_term_items") or []
    kept: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        exp = item.get("expires_at")
        if isinstance(exp, str):
            try:
                dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                if dt < now:
                    continue
            except ValueError:
                pass
        kept.append(item)
    memory["long_term_items"] = kept
    return memory


def apply_memory_item_patch(memory: dict[str, Any], items: list[dict[str, Any]] | None) -> None:
    if not items:
        return
    bucket = memory.setdefault("long_term_items", [])
    for item in items:
        if not isinstance(item, dict) or "kind" not in item or "text" not in item:
            continue
        entry = {
            "kind": str(item["kind"])[:64],
            "text": str(item["text"])[:2000],
        }
        if item.get("ttl_hours") is not None:
            try:
                hours = float(item["ttl_hours"])
                entry["expires_at"] = (
                    datetime.now(UTC) + timedelta(hours=hours)
                ).isoformat()
            except (TypeError, ValueError):
                pass
        bucket.append(entry)


def build_memory_prompt_block(memory: dict[str, Any]) -> str:
    parts: list[str] = []
    summary = memory.get("session_summary")
    if isinstance(summary, str) and summary.strip():
        parts.append("SESSION MEMORY (conversation summary, not evidence):\n" + summary.strip()[:2400])
    items = memory.get("long_term_items") or []
    lines = []
    for item in items[:12]:
        if isinstance(item, dict) and item.get("text"):
            lines.append(f"- [{item.get('kind', 'note')}] {item['text'][:400]}")
    if lines:
        parts.append("STRUCTURED MEMORY ITEMS (user-stated goals/notes, not evidence):\n" + "\n".join(lines))
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n\nUse DOCUMENT SOURCES below for factual claims; memory blocks are not evidence.\n"
