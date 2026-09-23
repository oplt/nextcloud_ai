"""One immutable authorization/filter contract for retrieval repository reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from ..core.security import AuthContext
from ..schemas.chat_schema import RetrievalFilters


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    auth: AuthContext
    document_ids: tuple[UUID, ...] | None = None
    filters: RetrievalFilters | None = None

    @classmethod
    def resolve(
        cls,
        *,
        auth: AuthContext,
        document_ids: Sequence[UUID] | None = None,
        filters: RetrievalFilters | None = None,
    ) -> "RetrievalScope":
        unique_ids = tuple(dict.fromkeys(document_ids or ())) or None
        return cls(auth=auth, document_ids=unique_ids, filters=filters)

    def repository_filters(self) -> dict[str, object]:
        filters = self.filters
        return {
            "connector_ids": filters.connector_ids if filters else None,
            "mime_types": filters.mime_types if filters else None,
            "path_prefixes": filters.path_prefixes if filters else None,
            "modified_after": filters.modified_after if filters else None,
            "modified_before": filters.modified_before if filters else None,
            "document_types": filters.document_types if filters else None,
            "business_domains": filters.business_domains if filters else None,
            "source_types": filters.source_types if filters else None,
        }
