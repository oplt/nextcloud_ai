"""Harness tests: no gold-label leak, fixture corpus, infra vs app errors."""

from __future__ import annotations

from uuid import UUID

import pytest

from backend.evals.fixture_loader import (
    fixture_uuid,
    load_fixture_bundle,
    resolve_ids,
)
from backend.evals.run_offline_eval import (
    EXIT_INFRA,
    EXIT_OK,
    InfrastructureError,
    _aggregate,
    main,
    run_fixture,
)
from backend.schemas.chat_schema import ChatSource


def test_fixture_bundle_loads_seeded_corpus() -> None:
    bundle = load_fixture_bundle()
    assert len(bundle.documents) >= 8
    assert len(bundle.identities) >= 3
    assert len(bundle.gold) >= 8
    vacation = bundle.documents_by_key["vacation_policy_2024"]
    assert vacation.document_id == fixture_uuid("doc:vacation_policy_2024")


def test_gold_ids_resolve_without_production_uuids() -> None:
    bundle = load_fixture_bundle()
    row = next(r for r in bundle.gold if r.id == "g1_vacation_carryover")
    resolved = resolve_ids(row.expected_document_ids)
    assert len(resolved) == 1
    UUID(resolved[0])  # valid UUID
    assert row.request_document_ids == []


def test_fixture_retrieval_does_not_need_request_scope_for_gold() -> None:
    bundle = load_fixture_bundle()
    records = run_fixture(bundle, with_answer=False, top_k=6)
    by_id = {rec["id"]: rec for rec in records}
    hit = by_id["g1_vacation_carryover"]
    assert hit["mode"] == "fixture"
    assert hit["request_document_ids"] == []
    assert hit["answer_eval"] == "skipped_retrieval_only"
    assert hit["answer_correctness"] is None
    assert hit["recall@6"] == 1.0


def test_explicit_scope_row_sets_request_ids_only() -> None:
    bundle = load_fixture_bundle()
    row = next(r for r in bundle.gold if r.id == "g9_scoped_vacation")
    assert row.request_document_ids == ["doc:vacation_policy_2024"]
    assert row.expected_document_ids == ["doc:vacation_policy_2024"]
    records = run_fixture(bundle, with_answer=False)
    scoped = next(rec for rec in records if rec["id"] == "g9_scoped_vacation")
    assert scoped["request_document_ids"] == resolve_ids(row.request_document_ids)


def test_acl_bob_cannot_see_alice_private() -> None:
    bundle = load_fixture_bundle()
    alice_doc = str(bundle.documents_by_key["alice_private_note"].document_id)
    records = run_fixture(bundle, with_answer=True)
    bob = next(rec for rec in records if rec["id"] == "g10_acl_bob_denied")
    alice = next(rec for rec in records if rec["id"] == "g11_acl_alice_allowed")
    assert bob["identity"] == "bob"
    assert alice_doc not in bob["retrieved_document_ids"]
    assert bob["abstention"] == 1.0
    assert alice["identity"] == "alice"
    assert alice_doc in alice["retrieved_document_ids"]
    assert alice["recall@6"] == 1.0


def test_unanswerable_abstains_in_fixture_answer_mode() -> None:
    bundle = load_fixture_bundle()
    records = run_fixture(bundle, with_answer=True)
    case = next(rec for rec in records if rec["id"] == "g8_unanswerable")
    assert case["abstention"] == 1.0
    assert case["recall@6"] is None
    assert case["citation_support"] is None
    assert "could not verify" in (case.get("answer") or "").lower()


def test_cli_fixture_mode_exit_ok(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--mode", "fixture", "--summary-only"])
    assert code == EXIT_OK
    captured = capsys.readouterr()
    assert "recall@6" in captured.out


def test_db_label_leak_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """expected_document_ids must never be passed as retrieval document_ids."""
    import asyncio

    from backend.evals import run_offline_eval as harness

    calls: list[dict[str, object]] = []

    class FakeResult:
        sources: list[object] = []
        retrieval_debug: dict[str, object] = {}

    class FakeService:
        def __init__(self, session: object) -> None:
            self.session = session

        async def retrieve(self, **kwargs: object) -> FakeResult:
            calls.append(dict(kwargs))
            return FakeResult()

    class FakeSession:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            return None

    import backend.db.session as db_session
    import backend.services.retrieval_service as retrieval_mod

    monkeypatch.setattr(db_session, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(retrieval_mod, "RetrievalService", FakeService)

    bundle = load_fixture_bundle()
    unscoped = next(r for r in bundle.gold if r.id == "g1_vacation_carryover")
    scoped = next(r for r in bundle.gold if r.id == "g9_scoped_vacation")
    bundle.gold = [unscoped, scoped]

    records = asyncio.run(harness._run_db_cases(bundle, with_answer=False, top_k=6))
    assert len(records) == 2
    assert len(calls) == 2

    # Unscoped gold case: document_ids must be None (not gold expected IDs).
    assert calls[0].get("document_ids") is None
    gold_expected = set(resolve_ids(unscoped.expected_document_ids))
    assert gold_expected  # sanity
    # Scoped case: only explicit request_document_ids.
    scoped_ids = [str(x) for x in calls[1]["document_ids"]]  # type: ignore[index]
    assert scoped_ids == resolve_ids(scoped.request_document_ids)
    assert scoped_ids == resolve_ids(scoped.expected_document_ids)


def test_db_answer_mode_verifies_answer_and_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Answer metrics use verified output and cited sources, not all retrievals."""
    import asyncio

    from backend.evals import run_offline_eval as harness

    bundle = load_fixture_bundle()
    row = next(r for r in bundle.gold if r.id == "g1_vacation_carryover")
    bundle.gold = [row]
    document = bundle.documents_by_key["vacation_policy_2024"]
    chunk = document.chunks[0]
    distractor = bundle.documents_by_key["distractor_lunch_menu"]
    distractor_chunk = distractor.chunks[0]
    source = ChatSource(
        chunk_id=chunk.chunk_id,
        document_id=document.document_id,
        file_name=document.title,
        file_path=document.file_path,
        page_number=chunk.page_number,
        section_title=chunk.section_title,
        snippet=chunk.text,
        content=chunk.text,
        distance=0.1,
        score=0.9,
    )
    distractor_source = ChatSource(
        chunk_id=distractor_chunk.chunk_id,
        document_id=distractor.document_id,
        file_name=distractor.title,
        file_path=distractor.file_path,
        page_number=distractor_chunk.page_number,
        section_title=distractor_chunk.section_title,
        snippet=distractor_chunk.text,
        content=distractor_chunk.text,
        distance=0.2,
        score=0.8,
    )

    class FakeResult:
        sources = [source, distractor_source]
        retrieval_debug: dict[str, object] = {}

    class FakeService:
        def __init__(self, session: object) -> None:
            self.session = session

        async def retrieve(self, **_kwargs: object) -> FakeResult:
            return FakeResult()

    class FakeSession:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            return None

    class FakeLlm:
        async def generate(self, _prompt: str) -> str:
            return "Employees may carry over 5 unused vacation days in 2024 [1]."

        async def aclose(self) -> None:
            return None

    import backend.ai.llm_client as llm_mod
    import backend.db.session as db_session
    import backend.services.retrieval_service as retrieval_mod

    monkeypatch.setattr(db_session, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(retrieval_mod, "RetrievalService", FakeService)
    monkeypatch.setattr(llm_mod.LLMClientFactory, "create", lambda: FakeLlm())

    records = asyncio.run(harness._run_db_cases(bundle, with_answer=True, top_k=6))
    record = records[0]
    assert record["answer_mode"] == "generated_verified"
    assert record["verification"]["result"] == "passed"
    assert len(record["retrieved_document_ids"]) == 2
    assert record["citation_support"] == 1.0
    assert record["citation_recall"] == 1.0
    assert record["claim_support"] == 1.0
    assert record["answer_exclusion_ok"] == 1.0
    assert record["stage_latency_seconds"]["verification"] >= 0.0


def test_aggregate_reports_each_stage_latency() -> None:
    summary = _aggregate(
        [
            {
                "stage_latency_seconds": {
                    "retrieval": 0.2,
                    "answer": 0.4,
                    "verification": 0.1,
                },
                "citation_recall": 1.0,
                "answer_exclusion_ok": 1.0,
            }
        ]
    )
    assert summary["stage_latency_mean_seconds"] == {
        "answer": 0.4,
        "retrieval": 0.2,
        "verification": 0.1,
    }
    assert summary["stage_latency_percentiles_seconds"]["retrieval"] == {
        "p50": 0.2,
        "p95": 0.2,
        "p99": 0.2,
    }
    assert summary["means"]["citation_recall"] == 1.0


def test_infrastructure_error_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.evals import run_offline_eval as harness

    async def boom(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise InfrastructureError("postgres refused connection")

    monkeypatch.setattr(harness, "_run_db_cases", boom)
    code = main(["--mode", "retrieval"])
    assert code == EXIT_INFRA
