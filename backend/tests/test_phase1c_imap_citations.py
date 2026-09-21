"""Phase 1C: IMAP inventory vs bounded fetch; no delete on partial."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.connectors.email.imap_client import (
    ImapFetchResult,
    ImapMessagePayload,
    MailboxInventory,
)
from backend.db.repo.document import DocumentRepository
from backend.schemas.chat_schema import ChatSource
from backend.services.chat_service import ChatService


class _FakeDoc:
    def __init__(
        self,
        *,
        imap_uid: str | None,
        mailbox: str = "INBOX",
        uidvalidity: int | None = 1,
        source_kind: str = "email_message",
    ) -> None:
        self.id = uuid4()
        self.connector_id = uuid4()
        self.is_deleted = False
        self.sync_status = "synced"
        meta: dict[str, object] = {"source_kind": source_kind}
        if imap_uid is not None:
            meta["imap_uid"] = imap_uid
        if mailbox:
            meta["imap_mailbox"] = mailbox
        if uidvalidity is not None:
            meta["imap_uidvalidity"] = uidvalidity
        self.metadata_json = meta


class _FakeResult:
    def __init__(self, docs: list[_FakeDoc]) -> None:
        self._docs = docs

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._docs))


class _FakeSession:
    def __init__(self, docs: list[_FakeDoc]) -> None:
        self.docs = docs
        self.flushed = False

    async def execute(self, _stmt):  # noqa: ANN001
        return _FakeResult(self.docs)

    async def flush(self) -> None:
        self.flushed = True


@pytest.mark.asyncio
async def test_mark_deleted_only_uids_absent_from_complete_inventory() -> None:
    docs = [
        _FakeDoc(imap_uid="1"),
        _FakeDoc(imap_uid="2"),
        _FakeDoc(imap_uid="150"),  # older than fetch window
    ]
    session = _FakeSession(docs)
    repo = DocumentRepository(session)  # type: ignore[arg-type]

    deleted = await repo.mark_deleted_missing_imap_uids(
        connector_id=docs[0].connector_id,
        present_uids=["1", "2", "150"],
        mailbox="INBOX",
        uidvalidity=1,
    )
    assert deleted == 0
    assert all(not d.is_deleted for d in docs)


@pytest.mark.asyncio
async def test_mark_deleted_removes_expunged_uid() -> None:
    docs = [
        _FakeDoc(imap_uid="1"),
        _FakeDoc(imap_uid="99"),
    ]
    session = _FakeSession(docs)
    repo = DocumentRepository(session)  # type: ignore[arg-type]

    deleted = await repo.mark_deleted_missing_imap_uids(
        connector_id=docs[0].connector_id,
        present_uids=["1"],
        mailbox="INBOX",
        uidvalidity=1,
    )
    assert deleted == 1
    assert docs[0].is_deleted is False
    assert docs[1].is_deleted is True
    assert docs[1].sync_status == "deleted"


@pytest.mark.asyncio
async def test_mark_deleted_skips_across_uidvalidity_epoch() -> None:
    docs = [_FakeDoc(imap_uid="1", uidvalidity=1)]
    session = _FakeSession(docs)
    repo = DocumentRepository(session)  # type: ignore[arg-type]

    deleted = await repo.mark_deleted_missing_imap_uids(
        connector_id=docs[0].connector_id,
        present_uids=[],
        mailbox="INBOX",
        uidvalidity=2,
    )
    assert deleted == 0
    assert docs[0].is_deleted is False


@pytest.mark.asyncio
async def test_mark_deleted_retains_legacy_docs_without_imap_uid() -> None:
    docs = [_FakeDoc(imap_uid=None)]
    docs[0].metadata_json = {"source_kind": "email_message"}
    session = _FakeSession(docs)
    repo = DocumentRepository(session)  # type: ignore[arg-type]

    deleted = await repo.mark_deleted_missing_imap_uids(
        connector_id=docs[0].connector_id,
        present_uids=["1"],
        mailbox="INBOX",
        uidvalidity=1,
    )
    assert deleted == 0


def test_fetch_result_separates_inventory_from_body_window() -> None:
    inventory = MailboxInventory(
        mailbox="INBOX",
        uidvalidity=42,
        uids=[str(i) for i in range(1, 151)],
        complete=True,
        search_criteria="ALL",
    )
    messages = [
        ImapMessagePayload(uid=str(i), raw_message=b"x") for i in range(51, 151)
    ]
    result = ImapFetchResult(
        inventory=inventory,
        messages=messages,
        fetch_failed_uids=["50"],
        fetch_truncated=True,
    )
    assert result.inventory.complete is True
    assert len(result.inventory.uids) == 150
    assert len(result.messages) == 100
    assert result.fetch_truncated is True
    # Deletion drivers must use inventory.uids, never the body window alone.
    assert set(m.uid for m in result.messages) < set(result.inventory.uids)


def test_incomplete_inventory_must_not_drive_deletes() -> None:
    inventory = MailboxInventory(
        mailbox="INBOX",
        uidvalidity=1,
        uids=["1"],
        complete=False,
        search_criteria="ALL",
    )
    assert inventory.complete is False


# --- Citation support (lunch ≠ invoice) ---


def _src(content: str) -> ChatSource:
    return ChatSource(
        chunk_id=uuid4(),
        document_id=uuid4(),
        file_name="note.txt",
        file_path="/note.txt",
        page_number=1,
        section_title=None,
        snippet=content,
        distance=0.1,
        score=0.9,
        heading_path=None,
        content=content,
    )


def test_unrelated_lunch_source_does_not_support_invoice_claim() -> None:
    service = object.__new__(ChatService)
    lunch = _src("Lunch is served at noon.")
    answer = "The invoice total is EUR 999999."

    selected = ChatService._select_supporting_sources(
        question="What is the invoice total?",
        answer=answer,
        sources=[lunch],
    )
    assert selected == []

    assert (
        service._answer_is_supported(
            question="What is the invoice total?",
            answer=answer,
            cited_sources=[lunch],
        )
        is False
    )

    out, sources, verification = service._verify_and_normalize_answer(
        question="What is the invoice total?",
        answer=answer,
        sources=[lunch],
        shadow_mode=False,
        trace_id="test-trace",
    )
    assert sources == []
    assert "[1]" not in out
    assert verification["result"] == "no_inline_citations"
    assert verification.get("auto_citation_applied") is not True


def test_matching_invoice_source_can_auto_cite() -> None:
    service = object.__new__(ChatService)
    invoice = _src("Invoice INV-42 total amount EUR 999999 payable by wire.")
    answer = "The invoice total is EUR 999999."

    selected = ChatService._select_supporting_sources(
        question="What is the invoice total?",
        answer=answer,
        sources=[invoice],
    )
    assert selected == [invoice]

    out, sources, verification = service._verify_and_normalize_answer(
        question="What is the invoice total?",
        answer=answer,
        sources=[invoice],
        shadow_mode=False,
        trace_id="test-trace",
    )
    assert sources == [invoice]
    assert "[1]" in out
    assert verification["result"] == "auto_cited"
