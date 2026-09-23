"""Resolve hard chat scope and completeness-aware document catalog branches."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.security import AuthContext
from ..schemas.chat_schema import ChatAskRequest, ChatDocumentResult
from .chat_completion import merge_document_ids
from .document_search_service import DocumentSearchService


@dataclass(slots=True)
class ChatScopePlan:
    retrieval_document_ids: list[UUID] | None
    retrieval_preferred_document_ids: list[UUID] | None
    active_context_document_ids: list[UUID]
    filename_scoped_document_ids: list[UUID] = field(default_factory=list)
    filename_references: list[str] = field(default_factory=list)
    filename_scope_attempted: bool = False
    document_results: list[ChatDocumentResult] = field(default_factory=list)
    answer: str | None = None
    verification: dict[str, object] | None = None
    retrieval_debug: dict[str, object] = field(default_factory=dict)
    catalog_answered: bool = False


def parse_document_ids(document_ids: list[str] | None) -> list[UUID]:
    parsed_ids: list[UUID] = []
    seen_ids: set[UUID] = set()
    for raw_id in document_ids or []:
        if not raw_id:
            continue
        try:
            parsed_id = UUID(str(raw_id))
        except ValueError:
            continue
        if parsed_id in seen_ids:
            continue
        seen_ids.add(parsed_id)
        parsed_ids.append(parsed_id)
    return parsed_ids


def build_document_search_answer(
    results: list[ChatDocumentResult], *, total: int | None = None
) -> str:
    shown = results[:8]
    if total is None:
        header = "I found these matching documents:"
    elif total > len(shown):
        header = (
            f"Matched {total} documents. Showing {len(shown)}. "
            "This list is not the full set."
        )
    else:
        header = f"Matched {total} documents:"
    return "\n".join(
        [header]
        + [
            f"[{index}] {item.file_name} - {item.file_path}"
            for index, item in enumerate(shown, start=1)
        ]
    )


async def plan_chat_scope(
    *,
    session: AsyncSession,
    auth: AuthContext,
    request: ChatAskRequest,
    retrieval_query: str,
    is_follow_up: bool,
    memory: dict[str, object],
    requested_active_context_document_ids: list[UUID],
    follow_up_document_ids: list[UUID],
    active_context_document_ids: list[UUID],
    shadow_mode: bool,
    trace_id: str,
) -> ChatScopePlan:
    explicit_document_ids = request.document_ids or None
    lock_ids = parse_document_ids(
        [str(value) for value in (memory.get("focus_lock_document_ids") or [])]
    )
    pinned_scope = explicit_document_ids or (lock_ids or None)
    catalog = DocumentSearchService(session)
    filename_references: list[str] = []
    filename_scoped_document_ids: list[UUID] = []
    filename_scope_attempted = False
    debug: dict[str, object] = {}

    if pinned_scope is None:
        filename_references = catalog.extract_file_references(retrieval_query)
        if filename_references:
            filename_scope_attempted = True
            search_results = await catalog.search(
                query=" ".join(filename_references),
                auth=auth,
                filters=request.retrieval_filters,
                limit=settings.RAG_FINAL_TOP_N,
            )
            filename_matches = [
                result
                for result in search_results
                if catalog.document_matches_file_reference(
                    result.document, filename_references
                )
            ]
            filename_scoped_document_ids = [
                UUID(str(result.document.id)) for result in filename_matches
            ]
            if filename_matches:
                active_context_document_ids = merge_document_ids(
                    filename_scoped_document_ids,
                    follow_up_document_ids,
                )
            debug["filename_scope"] = {
                "applied": bool(filename_matches),
                "references": filename_references,
                "matched_documents": len(filename_scoped_document_ids),
            }

    hard_scope = pinned_scope or (filename_scoped_document_ids or None)
    document_results: list[ChatDocumentResult] = []
    answer: str | None = None
    verification: dict[str, object] | None = None
    catalog_answered = False
    if hard_scope is None and catalog.is_exhaustive_catalog_query(retrieval_query):
        catalog_answered = True
        total = await catalog.count(
            query=retrieval_query,
            auth=auth,
            filters=request.retrieval_filters,
        )
        search_results = await catalog.search(
            query=retrieval_query,
            auth=auth,
            filters=request.retrieval_filters,
            limit=settings.RAG_FINAL_TOP_N,
        )
        document_results = [
            ChatDocumentResult.model_validate(result.as_dict())
            for result in search_results
        ]
        answer = build_document_search_answer(document_results, total=total)
        verification = {
            "result": "document_catalog",
            "matched_total": total,
            "shown": len(document_results),
            "complete": total <= len(document_results),
            "shadow_mode": shadow_mode,
            "trace_id": trace_id,
        }
        debug = {
            "document_search": {
                "applied": True,
                "intent": "exhaustive",
                "matched_total": total,
                "result_count": len(document_results),
            }
        }
    elif hard_scope is None and catalog.is_document_discovery_query(retrieval_query):
        search_results = await catalog.search(
            query=retrieval_query,
            auth=auth,
            filters=request.retrieval_filters,
            limit=settings.RAG_FINAL_TOP_N,
        )
        document_results = [
            ChatDocumentResult.model_validate(result.as_dict())
            for result in search_results
        ]
        if document_results:
            active_context_document_ids = merge_document_ids(
                [UUID(str(item.document_id)) for item in document_results],
                follow_up_document_ids,
            )
            answer = build_document_search_answer(document_results)
            verification = {
                "result": "document_search",
                "shadow_mode": shadow_mode,
                "trace_id": trace_id,
            }
            debug = {
                "document_search": {
                    "applied": True,
                    "intent": "navigation",
                    "result_count": len(document_results),
                }
            }

    retrieval_document_ids = explicit_document_ids
    retrieval_preferred_document_ids = None
    if lock_ids and explicit_document_ids is None:
        retrieval_document_ids = lock_ids
    if filename_scoped_document_ids and explicit_document_ids is None and not lock_ids:
        retrieval_document_ids = filename_scoped_document_ids
    if (
        requested_active_context_document_ids
        and is_follow_up
        and explicit_document_ids is None
        and not lock_ids
        and not filename_scoped_document_ids
    ):
        retrieval_document_ids = requested_active_context_document_ids
    elif (
        follow_up_document_ids
        and is_follow_up
        and explicit_document_ids is None
        and not lock_ids
        and not filename_scoped_document_ids
    ):
        retrieval_preferred_document_ids = follow_up_document_ids

    return ChatScopePlan(
        retrieval_document_ids=retrieval_document_ids,
        retrieval_preferred_document_ids=retrieval_preferred_document_ids,
        active_context_document_ids=active_context_document_ids,
        filename_scoped_document_ids=filename_scoped_document_ids,
        filename_references=filename_references,
        filename_scope_attempted=filename_scope_attempted,
        document_results=document_results,
        answer=answer,
        verification=verification,
        retrieval_debug=debug,
        catalog_answered=catalog_answered,
    )
