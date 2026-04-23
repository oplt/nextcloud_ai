"""Provenance and evidence-tier labels for product intelligence (insights, tasks, graph edges)."""

from __future__ import annotations

from typing import Any

METHOD_FILENAME_KEYWORDS = "filename_path_keyword_signals"
METHOD_BODY_KEYWORDS = "body_keyword_signals"
METHOD_REGEX_STRUCTURE = "regex_structure"
METHOD_EXTRACTIVE_SUMMARY = "extractive_summary"
METHOD_SENTENCE_MARKER_PARSE = "sentence_marker_parse"
METHOD_STATIC_CONTROL_CHECKLIST = "static_control_keyword_checklist"
METHOD_LINE_ACTION_PARSE = "line_action_item_parse"
METHOD_GRAPH_CO_MENTION = "same_document_graph_co_mention"

EVIDENCE_SUGGESTION = "suggestion"
EVIDENCE_HEURISTIC_PARSE = "heuristic_parse"
EVIDENCE_DOCUMENT_SIGNAL = "document_signal"


def provenance_block(
    *,
    methods: list[str],
    evidence_tier: str,
    notes: str | None = None,
) -> dict[str, Any]:
    block: dict[str, Any] = {"methods": list(methods), "evidence_tier": evidence_tier}
    if notes:
        block["notes"] = notes
    return {"provenance": block}


def merge_provenance(payload: dict[str, Any] | None, block: dict[str, Any]) -> dict[str, Any]:
    base = dict(payload or {})
    base.update(block)
    return base


def task_metadata_with_provenance(
    base: dict[str, Any] | None,
    *,
    methods: list[str],
    evidence_tier: str,
    presentation: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    meta = dict(base or {})
    meta.update(provenance_block(methods=methods, evidence_tier=evidence_tier, notes=notes))
    if presentation is not None:
        meta["presentation"] = presentation
    return meta
