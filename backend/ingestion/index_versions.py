"""Optimistic index generation helpers for concurrent ingest/publish."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Document


class StaleIndexGenerationError(RuntimeError):
    """Raised when a worker tries to publish after a newer generation started."""


@dataclass(frozen=True, slots=True)
class IndexAttempt:
    document_id: str
    generation: int


_UNSET = object()


async def begin_index_attempt(
    session: AsyncSession,
    document: Document,
    *,
    expected_version_tag: str | None | object = _UNSET,
) -> IndexAttempt:
    """Atomically reserve a generation while holding the document row lock."""
    await session.flush()
    stmt = update(Document).where(Document.id == document.id)
    if expected_version_tag is not _UNSET:
        if expected_version_tag is None:
            stmt = stmt.where(Document.version_tag.is_(None))
        else:
            stmt = stmt.where(Document.version_tag == expected_version_tag)
    result = await session.execute(
        stmt.values(index_generation=Document.index_generation + 1).returning(
            Document.index_generation
        )
    )
    generation_value = result.scalar_one_or_none()
    if generation_value is None:
        raise StaleIndexGenerationError(
            "source version changed before index generation could be reserved"
        )
    generation = int(generation_value)
    document.index_generation = generation
    return IndexAttempt(document_id=str(document.id), generation=generation)


def assert_publish_allowed(document: Document, attempt: IndexAttempt) -> None:
    if str(document.id) != attempt.document_id:
        raise StaleIndexGenerationError("document id mismatch for index attempt")
    if int(document.index_generation or 0) != attempt.generation:
        raise StaleIndexGenerationError(
            f"stale index generation {attempt.generation}; "
            f"current={document.index_generation}"
        )


def mark_published(document: Document, attempt: IndexAttempt) -> None:
    assert_publish_allowed(document, attempt)
    document.published_generation = attempt.generation
