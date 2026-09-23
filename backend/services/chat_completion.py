"""Typed finalization and persistence for one completed chat request."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..core import observability
from ..db.models import ChatMessage, ChatSession
from ..db.repo.chat import ChatMessageRepository
from ..schemas.chat_schema import (
    ChatAskRequest,
    ChatAskResponse,
    ChatDocumentResult,
    ChatSource,
)


@dataclass(slots=True)
class ChatCompletion:
    answer: str
    sources: list[ChatSource]
    document_results: list[ChatDocumentResult]
    active_context_document_ids: list[UUID]
    follow_up_document_ids: list[UUID]
    retrieval_query: str
    trace_id: str
    llm_provider: str
    llm_model_id: str
    prompt_version: str
    retrieval_settings: dict[str, object]
    verification: dict[str, object] | None
    retrieval_debug: dict[str, object]
    memory_applied: dict[str, object]
    llm_usage: dict[str, object]
    memory: dict[str, object]
    shadow_mode: bool
    rerank_stats: dict[str, object] = field(default_factory=dict)
    candidate_source_count: int | None = None
    retrieval_error_type: str | None = None
    llm_error_type: str | None = None


def merge_document_ids(*document_groups: list[UUID]) -> list[UUID]:
    merged: list[UUID] = []
    seen: set[str] = set()
    for group in document_groups:
        for document_id in group:
            key = str(document_id)
            if key not in seen:
                seen.add(key)
                merged.append(document_id)
    return merged


def document_ids_from_sources(sources: list[ChatSource]) -> list[UUID]:
    return merge_document_ids(
        [UUID(str(source.document_id)) for source in sources if source.document_id]
    )


def active_context_documents(
    sources: list[ChatSource], active_document_ids: list[UUID]
) -> list[dict[str, str]]:
    by_document: dict[str, dict[str, str]] = {}
    for source in sources:
        key = str(source.document_id)
        by_document.setdefault(
            key,
            {
                "document_id": key,
                "file_name": source.file_name,
                "file_path": source.file_path,
            },
        )
    return [
        by_document[str(document_id)]
        for document_id in active_document_ids
        if str(document_id) in by_document
    ]


def answer_confidence(
    sources: list[ChatSource], verification: dict[str, object] | None
) -> float | None:
    if verification is None:
        return None
    result = verification.get("result")
    top = max((source.score for source in sources), default=0.0)
    if result == "passed":
        return round(min(0.99, 0.52 + 0.42 * top), 3)
    if result in {"insufficient_answer", "empty_llm"}:
        return round(0.15 + 0.25 * top, 3)
    if result in {"no_sources", "no_inline_citations", "support_check_failed"}:
        return round(0.12 + 0.2 * top, 3)
    return round(0.2 + 0.15 * top, 3)


async def finalize_chat_completion(
    *,
    session: AsyncSession,
    message_repo: ChatMessageRepository,
    chat_session: ChatSession,
    user_message: ChatMessage,
    request: ChatAskRequest,
    completion: ChatCompletion,
) -> ChatAskResponse:
    cited_ids = document_ids_from_sources(completion.sources)
    active_ids = completion.active_context_document_ids
    if cited_ids:
        active_ids = merge_document_ids(cited_ids, completion.follow_up_document_ids)
    confidence = answer_confidence(completion.sources, completion.verification)
    _record_completion_metrics(completion, confidence)

    metadata: dict[str, object] = {
        "trace_id": completion.trace_id,
        "llm_provider": completion.llm_provider,
        "llm_model_id": completion.llm_model_id,
        "llm_usage": completion.llm_usage,
        "grounded_prompt_version": completion.prompt_version,
        "retrieval": completion.retrieval_settings,
        "verification": completion.verification,
        "retrieval_debug": completion.retrieval_debug,
        "memory_applied": completion.memory_applied,
        "answer_confidence": confidence,
    }
    if completion.retrieval_error_type:
        metadata["retrieval_error_type"] = completion.retrieval_error_type
    if completion.llm_error_type:
        metadata["llm_error_type"] = completion.llm_error_type

    chat_session.memory_json = dict(completion.memory)
    chat_session.updated_at = datetime.now(timezone.utc)
    assistant_message = ChatMessage(
        session_id=chat_session.id,
        role="assistant",
        content=completion.answer,
        citations_json=(
            [source.model_dump(mode="json") for source in completion.sources] or None
        ),
        model_name=f"{completion.llm_provider}:{completion.llm_model_id}",
        generation_metadata_json=metadata,
    )
    await message_repo.add(assistant_message, flush=True)
    await session.commit()
    await session.refresh(assistant_message)
    await session.refresh(chat_session)

    return ChatAskResponse(
        session_id=chat_session.id,
        answer=completion.answer,
        answer_confidence=confidence,
        sources=completion.sources,
        document_results=completion.document_results,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        parent_message_id=request.parent_message_id,
        request_id=request.request_id,
        cited_sources=completion.sources,
        active_context_document_ids=[str(item) for item in active_ids],
        active_context_documents=active_context_documents(
            completion.sources, active_ids
        ),
        conversation_query=completion.retrieval_query,
        generation_trace_id=completion.trace_id,
        llm_provider=completion.llm_provider,
        llm_model_id=completion.llm_model_id,
        grounded_prompt_version=completion.prompt_version,
        retrieval_settings=completion.retrieval_settings,
        verification=completion.verification,
        retrieval_debug=completion.retrieval_debug or None,
        memory_applied=completion.memory_applied,
    )


def _record_completion_metrics(
    completion: ChatCompletion, confidence: float | None
) -> None:
    if completion.verification:
        observability.record_rag_verification(
            result=str(completion.verification.get("result")),
            shadow_mode=completion.shadow_mode,
        )
        if completion.shadow_mode and completion.verification.get("shadow_kept_raw"):
            observability.record_rag_shadow_override(reason="no_inline_citations")
        if completion.shadow_mode and completion.verification.get(
            "shadow_keeps_citation_answer"
        ):
            observability.record_rag_shadow_override(reason="support_check_failed")
    if completion.candidate_source_count is not None:
        observability.record_rag_citation_filter(
            before_count=completion.candidate_source_count,
            after_count=len(completion.sources),
        )
    if completion.rerank_stats:
        observability.record_rag_rerank_event(
            order_changed=bool(completion.rerank_stats.get("order_changed")),
            content_truncated_count=int(
                completion.rerank_stats.get("sources_content_truncated") or 0
            ),
        )
    observability.record_rag_low_confidence_answer(confidence=confidence)
