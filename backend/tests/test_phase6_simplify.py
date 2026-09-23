"""Phase 6: dead-path removal, shared lexical JSON, filter kwargs, extractor module."""

from __future__ import annotations

import importlib
import sys
import warnings
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.core.security import AuthContext
from backend.rag.evidence_extractor import EvidenceExtractor
from backend.rag.lexical import semantic_json_text
from backend.rag.scope import RetrievalScope
from backend.rag.stores import retrieval_filter_kwargs
from backend.schemas.chat_schema import ChatSource, RetrievalFilters

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_retrieval_filter_kwargs_none() -> None:
    kwargs = retrieval_filter_kwargs(None)
    assert kwargs["connector_ids"] is None
    assert kwargs["source_types"] is None


def test_retrieval_filter_kwargs_populated() -> None:
    from uuid import uuid4

    cid = uuid4()
    filters = RetrievalFilters(connector_ids=[cid], path_prefixes=["/a"])
    kwargs = retrieval_filter_kwargs(filters)
    assert kwargs["connector_ids"] == [cid]
    assert kwargs["path_prefixes"] == ["/a"]


def test_retrieval_scope_deduplicates_hard_document_ids() -> None:
    document_id = uuid4()
    scope = RetrievalScope.resolve(
        auth=AuthContext(user_id="user", auth_provider="local"),
        document_ids=[document_id, document_id],
    )
    assert scope.document_ids == (document_id,)


def test_reranker_uses_semantic_json_allowlist() -> None:
    # ContextReranker imports semantic_json_text — no local _json_text.
    import backend.rag.reranker as reranker_mod

    assert not hasattr(reranker_mod, "_json_text")
    text = semantic_json_text(
        {"from": "a@b.c", "stored_payload_b64": "SHOULD_NOT_APPEAR" * 8}
    )
    assert "a@b.c" in text
    assert "SHOULD_NOT_APPEAR" not in text


def test_evidence_extractor_amount() -> None:
    from uuid import uuid4

    source = ChatSource(
        document_id=uuid4(),
        chunk_id=uuid4(),
        file_name="invoice.pdf",
        file_path="/invoice.pdf",
        content="Invoice total 120,50 EUR payable now",
        snippet="Invoice total 120,50 EUR",
        distance=0.1,
        score=0.9,
    )
    matches = EvidenceExtractor.amount_extractor([source])
    assert matches
    assert "120" in matches[0].value


def test_dead_helpers_removed() -> None:
    import backend.db.session as session_mod
    import backend.services.chat_service as chat_mod
    import backend.services.product_intelligence_service as intel_mod
    import backend.workers.indexing_tasks as tasks_mod

    assert not hasattr(session_mod, "run_async_safe")
    assert not hasattr(tasks_mod, "_run_logged_background_task")
    assert not hasattr(intel_mod.ProductIntelligenceService, "_classify_document")
    assert not hasattr(intel_mod.ProductIntelligenceService, "_suggested_owner_roles")
    assert not hasattr(
        intel_mod.ProductIntelligenceService, "_acceptance_criteria_for_task"
    )
    assert not hasattr(chat_mod.ChatService, "_source_evidence_lines")
    assert not hasattr(chat_mod.ChatService, "_entity_match_score")
    assert not hasattr(chat_mod.ChatService, "_compute_answer_confidence")
    assert not hasattr(chat_mod.ChatService, "_build_active_context_documents")
    assert not hasattr(EvidenceExtractor, "field_value_extractor")
    assert not hasattr(EvidenceExtractor, "table_row_extractor")


def test_compat_wrappers_emit_deprecation() -> None:
    from backend.parsers.document_parser import parse_odt_bytes
    from backend.services.query_writer import is_likely_follow_up
    from backend.ai.prompt_builder import available_domain_profiles

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert is_likely_follow_up("and the amount?", has_history=True) in {True, False}
        assert isinstance(available_domain_profiles(), tuple)
        # ODT wrapper warns even on invalid payload path — call after warn check on others
        assert any(issubclass(w.category, DeprecationWarning) for w in caught)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(ValueError):
            parse_odt_bytes(b"not-an-odt")
        assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_conversational_rag_and_uow_removed() -> None:
    import importlib.util

    assert (
        importlib.util.find_spec("backend.services.conversational_rag_service") is None
    )
    assert importlib.util.find_spec("backend.db.repo.uow") is None


def test_verified_dead_frontend_and_root_files_stay_removed() -> None:
    removed = (
        "frontend/src/App.css",
        "frontend/src/assets/react.svg",
        "frontend/src/pages/ChatPage.tsx",
        "package-lock.json",
    )
    assert all(not (REPO_ROOT / path).exists() for path in removed)
    assert (REPO_ROOT / "frontend/public/vite.svg").exists()


def test_cleanup_stale_connections_retained_noop() -> None:
    from backend.workers.indexing_tasks import cleanup_stale_connections
    from backend.workers.celery_app import celery_app

    result = cleanup_stale_connections()
    assert result["skipped"] is True
    assert result.get("deprecated") is True
    scheduled_tasks = {
        value.get("task") for value in celery_app.conf.beat_schedule.values()
    }
    assert (
        "backend.workers.indexing_tasks.cleanup_stale_connections"
        not in scheduled_tasks
    )


@pytest.mark.parametrize(
    ("shim", "symbol", "canonical"),
    [
        ("nextcloud_client", "AsyncNextcloudClient", "client"),
        ("nextcloud_events", "router", "webhooks"),
        ("nextcloud_permissions", "NextcloudPermissionService", "permissions"),
        ("nextcloud_sync", "NextcloudSyncService", "sync"),
    ],
)
def test_nextcloud_compatibility_shims_warn_and_reexport(
    shim: str, symbol: str, canonical: str
) -> None:
    package = "backend.connectors.nextcloud"
    shim_name = f"{package}.{shim}"
    sys.modules.pop(shim_name, None)
    canonical_module = importlib.import_module(f"{package}.{canonical}")
    with pytest.warns(DeprecationWarning):
        shim_module = importlib.import_module(shim_name)
    assert getattr(shim_module, symbol) is getattr(canonical_module, symbol)


@pytest.mark.asyncio
async def test_chat_completion_component_persists_contract() -> None:
    from backend.db.models import ChatMessage, ChatSession
    from backend.services.chat_completion import (
        ChatCompletion,
        finalize_chat_completion,
    )
    from backend.schemas.chat_schema import ChatAskRequest

    source_document_id = uuid4()
    source = ChatSource(
        document_id=source_document_id,
        chunk_id=uuid4(),
        file_name="policy.pdf",
        file_path="/policy.pdf",
        snippet="Retention is seven years.",
        content="Retention is seven years.",
        distance=0.1,
        score=0.9,
    )
    chat_session = ChatSession(id=uuid4(), user_id=uuid4(), title="Policy")
    user_message = ChatMessage(
        id=uuid4(), session_id=chat_session.id, role="user", content="Retention?"
    )
    added: list[ChatMessage] = []

    class MessageRepo:
        async def add(self, message: ChatMessage, *, flush: bool) -> ChatMessage:
            assert flush is True
            message.id = uuid4()
            added.append(message)
            return message

    response = await finalize_chat_completion(
        session=AsyncMock(),
        message_repo=MessageRepo(),  # type: ignore[arg-type]
        chat_session=chat_session,
        user_message=user_message,
        request=ChatAskRequest(question="Retention?", request_id="req-1"),
        completion=ChatCompletion(
            answer="Retention is seven years. [1]",
            sources=[source],
            document_results=[],
            active_context_document_ids=[],
            follow_up_document_ids=[],
            retrieval_query="retention period",
            trace_id="trace-1",
            llm_provider="ollama",
            llm_model_id="model",
            prompt_version="v1",
            retrieval_settings={"top_k": 6},
            verification={"result": "passed"},
            retrieval_debug={},
            memory_applied={},
            llm_usage={"calls": 1},
            memory={"session_summary": "retention"},
            shadow_mode=False,
            candidate_source_count=1,
        ),
    )

    assert response.active_context_document_ids == [str(source_document_id)]
    assert response.answer_confidence is not None
    assert added[0].generation_metadata_json["trace_id"] == "trace-1"
    assert chat_session.memory_json == {"session_summary": "retention"}


def test_intelligence_task_builder_owns_candidate_materialization() -> None:
    import inspect

    from backend.services.intelligence_task_builder import IntelligenceTaskBuilder
    from backend.services.product_intelligence_service import ProductIntelligenceService

    assert hasattr(IntelligenceTaskBuilder, "populate_from_insights")
    build_src = inspect.getsource(ProductIntelligenceService._build_tasks)
    assert "populate_from_insights" in build_src
    assert "meeting_action_item" not in build_src
    assert len(build_src.splitlines()) < 40


def test_compat_inventory_reports_retained_noop_task() -> None:
    from backend.scripts.phase6_compat_inventory import inventory

    report = inventory()
    assert report["ok"] is True
    cleanup = report["cleanup_stale_connections"]
    assert cleanup["registered"] is True
    assert cleanup["on_beat_schedule"] is False
    assert cleanup["status"] == "retained_noop_compat"
    assert report["recommendation"]["remove_cleanup_task_now"] is False


def test_rollout_preflight_contracts() -> None:
    from backend.scripts.rollout_preflight import validate_rollout_contracts

    report = validate_rollout_contracts()
    assert report["alembic_heads"] == ["e5f6a7b8c9d0"]
    assert report["missing_routes"] == []
    assert report["missing_tasks"] == []


def test_intelligence_task_policies_are_data_driven() -> None:
    from backend.services.intelligence_task_policy import (
        acceptance_criteria,
        parse_task_date,
        suggested_owner_roles,
        suggested_reviewer_roles,
        task_title_from_excerpt,
    )

    assert suggested_owner_roles(
        queue_name="contracts", task_type="contract_deadline"
    ) == ["legal_counsel", "account_manager", "procurement_lead"]
    assert suggested_reviewer_roles(
        queue_name="compliance", task_type="compliance_gap"
    ) == ["compliance_reviewer", "security_reviewer"]
    criteria = acceptance_criteria(
        task_type="meeting_action_item", review_status="needs_review"
    )
    assert (
        next(item for item in criteria if item["key"] == "due_date_confirmed")[
            "required"
        ]
        is True
    )
    assert parse_task_date("2026-10-15") is not None
    assert len(task_title_from_excerpt("word " * 40, prefix="Review")) <= 101
