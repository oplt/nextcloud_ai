"""Optimistic index generation helpers for concurrent ingest/publish."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Document


class StaleIndexGenerationError(RuntimeError):
    """Raised when a worker tries to publish after a newer generation started."""


@dataclass(frozen=True, slots=True)
class IndexAttempt:
    document_id: str
    generation: int


async def begin_index_attempt(
    session: AsyncSession, document: Document
) -> IndexAttempt:
    """Bump generation so overlapping workers can detect staleness at publish."""
    document.index_generation = int(document.index_generation or 0) + 1
    await session.flush()
    return IndexAttempt(document_id=str(document.id), generation=document.index_generation)


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
