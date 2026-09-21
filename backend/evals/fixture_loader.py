"""Isolated eval fixture loader (no production DB UUIDs required).

Fixture keys like ``doc:vacation_policy_2024`` resolve to stable UUIDv5 values
under the ``nextcloud-ai-eval`` namespace. Gold ``expected_*`` fields are for
scoring only; ``request_document_ids`` is the only ID list that may scope
retrieval.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5, NAMESPACE_URL

from .offline_scorer import OfflineEvalRow, load_eval_rows

FIXTURES_DIR = Path(__file__).with_name("fixtures")
EVAL_NAMESPACE = uuid5(NAMESPACE_URL, "nextcloud-ai-eval")


def fixture_uuid(key: str) -> UUID:
    """Stable UUID for a fixture document/chunk/identity key."""
    normalized = key.strip()
    if normalized.startswith("doc:"):
        normalized = normalized[4:]
    elif normalized.startswith("chunk:"):
        normalized = normalized[6:]
    elif normalized.startswith("user:"):
        normalized = normalized[5:]
    return uuid5(EVAL_NAMESPACE, normalized)


def resolve_id(value: str) -> str:
    """Return a UUID string; pass through already-valid UUIDs."""
    text = str(value).strip()
    try:
        return str(UUID(text))
    except ValueError:
        return str(fixture_uuid(text))


def resolve_ids(values: list[str]) -> list[str]:
    return [resolve_id(value) for value in values]


@dataclass(frozen=True)
class FixtureChunk:
    key: str
    text: str
    page_number: int | None = None
    section_title: str | None = None
    heading_path: str | None = None

    @property
    def chunk_id(self) -> UUID:
        return fixture_uuid(f"chunk:{self.key}")


@dataclass(frozen=True)
class FixtureDocument:
    key: str
    title: str
    language: str
    mime_type: str
    file_path: str
    text: str
    tags: tuple[str, ...] = ()
    visible_to: tuple[str, ...] = ("alice", "bob", "admin")
    chunks: tuple[FixtureChunk, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def document_id(self) -> UUID:
        return fixture_uuid(f"doc:{self.key}")

    def chunk_ids(self) -> list[str]:
        return [str(chunk.chunk_id) for chunk in self.chunks]


@dataclass(frozen=True)
class FixtureIdentity:
    key: str
    username: str
    display_name: str
    is_superuser: bool = False
    role_name: str = "user"

    @property
    def user_id(self) -> UUID:
        return fixture_uuid(f"user:{self.key}")


@dataclass
class EvalFixtureBundle:
    documents: list[FixtureDocument]
    identities: list[FixtureIdentity]
    gold: list[OfflineEvalRow]
    documents_by_key: dict[str, FixtureDocument] = field(default_factory=dict)
    identities_by_key: dict[str, FixtureIdentity] = field(default_factory=dict)

    def resolve_gold_document_ids(self, row: OfflineEvalRow) -> list[str]:
        return resolve_ids(row.expected_document_ids)

    def resolve_request_document_ids(self, row: OfflineEvalRow) -> list[str]:
        return resolve_ids(row.request_document_ids)


def _parse_chunk(raw: dict[str, Any], doc_key: str, index: int) -> FixtureChunk:
    key = str(raw.get("key") or f"{doc_key}:c{index}")
    return FixtureChunk(
        key=key,
        text=str(raw.get("text") or ""),
        page_number=raw.get("page_number"),
        section_title=raw.get("section_title"),
        heading_path=raw.get("heading_path"),
    )


def _parse_document(raw: dict[str, Any]) -> FixtureDocument:
    key = str(raw["key"])
    chunk_raws = list(raw.get("chunks") or [])
    chunks = tuple(
        _parse_chunk(chunk, key, index) for index, chunk in enumerate(chunk_raws, start=1)
    )
    if not chunks and raw.get("text"):
        chunks = (
            FixtureChunk(key=f"{key}:c1", text=str(raw["text"]), page_number=1),
        )
    return FixtureDocument(
        key=key,
        title=str(raw.get("title") or key),
        language=str(raw.get("language") or "en"),
        mime_type=str(raw.get("mime_type") or "text/plain"),
        file_path=str(raw.get("file_path") or f"/fixtures/{key}.txt"),
        text=str(raw.get("text") or "\n\n".join(c.text for c in chunks)),
        tags=tuple(str(t) for t in (raw.get("tags") or [])),
        visible_to=tuple(str(v) for v in (raw.get("visible_to") or ["alice", "bob", "admin"])),
        chunks=chunks,
        metadata=dict(raw.get("metadata") or {}),
    )


def _parse_identity(raw: dict[str, Any]) -> FixtureIdentity:
    return FixtureIdentity(
        key=str(raw["key"]),
        username=str(raw.get("username") or raw["key"]),
        display_name=str(raw.get("display_name") or raw["key"]),
        is_superuser=bool(raw.get("is_superuser", False)),
        role_name=str(raw.get("role_name") or ("admin" if raw.get("is_superuser") else "user")),
    )


def load_corpus(path: Path | None = None) -> list[FixtureDocument]:
    corpus_path = path or (FIXTURES_DIR / "corpus.json")
    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    documents_raw = payload.get("documents") if isinstance(payload, dict) else payload
    return [_parse_document(raw) for raw in documents_raw]


def load_identities(path: Path | None = None) -> list[FixtureIdentity]:
    identities_path = path or (FIXTURES_DIR / "identities.json")
    payload = json.loads(identities_path.read_text(encoding="utf-8"))
    identities_raw = payload.get("identities") if isinstance(payload, dict) else payload
    return [_parse_identity(raw) for raw in identities_raw]


def load_fixture_bundle(
    *,
    gold_path: Path | None = None,
    corpus_path: Path | None = None,
    identities_path: Path | None = None,
) -> EvalFixtureBundle:
    documents = load_corpus(corpus_path)
    identities = load_identities(identities_path)
    gold = load_eval_rows(
        gold_path or Path(__file__).with_name("rag_gold.jsonl")
    )
    return EvalFixtureBundle(
        documents=documents,
        identities=identities,
        gold=gold,
        documents_by_key={doc.key: doc for doc in documents},
        identities_by_key={ident.key: ident for ident in identities},
    )


def documents_visible_to(bundle: EvalFixtureBundle, identity_key: str) -> list[FixtureDocument]:
    return [
        doc
        for doc in bundle.documents
        if identity_key in doc.visible_to or identity_key == "admin"
    ]
