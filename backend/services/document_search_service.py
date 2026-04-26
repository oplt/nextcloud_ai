from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security import AuthContext
from ..db.models import Document
from ..db.repo.document import DocumentRepository
from ..schemas.chat_schema import RetrievalFilters

_DISCOVERY_RE = re.compile(
    r"\b(find|show|list|search|locate|get)\b", flags=re.IGNORECASE
)
_TOKEN_RE = re.compile(r"[^\W\s]+(?:[-./_][^\W\s]+)*", flags=re.UNICODE)
_FILE_REFERENCE_RE = re.compile(
    r"\b[^\W\s][\w._-]{1,180}\.(?:pdf|docx?|xlsx?|pptx?|txt|csv|md|eml|odt)\b",
    flags=re.IGNORECASE,
)
_STOPWORDS = {
    "a",
    "all",
    "an",
    "and",
    "document",
    "documents",
    "file",
    "files",
    "find",
    "get",
    "list",
    "locate",
    "me",
    "search",
    "show",
    "the",
}


@dataclass(slots=True)
class DocumentSearchResult:
    document: Document
    score: float
    matched_fields: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "document_id": str(self.document.id),
            "file_name": self.document.file_name,
            "file_path": self.document.file_path,
            "document_type": self.document.document_type,
            "business_domain": self.document.business_domain,
            "modified_at": self.document.modified_at.isoformat()
            if self.document.modified_at
            else None,
            "score": self.score,
            "matched_fields": self.matched_fields,
        }


class DocumentSearchService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = DocumentRepository(session)

    async def search(
        self,
        *,
        query: str,
        auth: AuthContext,
        filters: RetrievalFilters | None = None,
        limit: int = 8,
    ) -> list[DocumentSearchResult]:
        terms = self.extract_terms(query)
        if not terms:
            return []
        documents = await self.repo.search_documents(
            auth=auth,
            terms=terms,
            connector_ids=filters.connector_ids if filters else None,
            path_prefixes=filters.path_prefixes if filters else None,
            modified_after=filters.modified_after if filters else None,
            modified_before=filters.modified_before if filters else None,
            document_types=filters.document_types if filters else None,
            business_domains=filters.business_domains if filters else None,
            source_types=filters.source_types if filters else None,
            limit=max(limit * 4, 20),
        )
        ranked = sorted(
            [self._score_document(document, terms) for document in documents],
            key=lambda item: item.score,
            reverse=True,
        )
        return [item for item in ranked if item.score > 0][:limit]

    @staticmethod
    def is_document_discovery_query(query: str) -> bool:
        lowered = query.lower()
        return bool(_DISCOVERY_RE.search(lowered)) and any(
            token not in _STOPWORDS for token in _TOKEN_RE.findall(lowered)
        )

    @staticmethod
    def extract_terms(query: str) -> list[str]:
        seen: set[str] = set()
        terms: list[str] = []
        for token in _TOKEN_RE.findall(query.lower()):
            if token in _STOPWORDS:
                continue
            if len(token) < 2 and not any(ch.isdigit() for ch in token):
                continue
            if token in seen:
                continue
            seen.add(token)
            terms.append(token)
            for part in re.split(r"[-./_]+", token):
                if (
                    part
                    and part != token
                    and part not in _STOPWORDS
                    and (len(part) >= 2 or any(ch.isdigit() for ch in part))
                    and part not in seen
                ):
                    seen.add(part)
                    terms.append(part)
        return terms

    @staticmethod
    def extract_file_references(query: str) -> list[str]:
        seen: set[str] = set()
        references: list[str] = []
        for match in _FILE_REFERENCE_RE.finditer(query):
            value = " ".join(match.group(0).strip(".,;:()[]{}<>\"'").split())
            lowered = value.lower()
            if not lowered or lowered in seen:
                continue
            seen.add(lowered)
            references.append(value)
        return references

    @staticmethod
    def document_matches_file_reference(
        document: Document, file_references: list[str]
    ) -> bool:
        if not file_references:
            return False
        file_name = (document.file_name or "").lower()
        file_path = (document.file_path or "").lower()
        for reference in file_references:
            normalized = reference.lower().strip()
            if not normalized:
                continue
            if normalized == file_name or file_path.endswith(f"/{normalized}"):
                return True
            stem = normalized.rsplit(".", 1)[0]
            if stem and (stem == file_name.rsplit(".", 1)[0] or stem in file_path):
                return True
        return False

    def _score_document(
        self, document: Document, terms: list[str]
    ) -> DocumentSearchResult:
        fields = {
            "file_name": document.file_name,
            "file_path": document.file_path,
            "document_type": document.document_type,
            "business_domain": document.business_domain,
            "metadata_json": _json_text(document.metadata_json),
            "extracted_fields_json": _json_text(document.extracted_fields_json),
            "content": " ".join(chunk.content for chunk in document.chunks[:6]),
        }
        weights = {
            "file_name": 1.0,
            "file_path": 0.8,
            "document_type": 1.2,
            "business_domain": 0.8,
            "metadata_json": 0.7,
            "extracted_fields_json": 1.4,
            "content": 0.6,
        }
        matched_fields: list[str] = []
        raw_score = 0.0
        for field, value in fields.items():
            haystack = (value or "").lower()
            hits = sum(1 for term in terms if term in haystack)
            if hits:
                matched_fields.append(field)
                raw_score += weights[field] * hits / max(len(terms), 1)
        lowered_name = (document.file_name or "").lower()
        lowered_path = (document.file_path or "").lower()
        for term in terms:
            if "." in term and (term == lowered_name or lowered_path.endswith(f"/{term}")):
                raw_score += 2.0
                if "file_name" not in matched_fields:
                    matched_fields.append("file_name")
                break
        return DocumentSearchResult(
            document=document,
            score=min(0.999, raw_score),
            matched_fields=matched_fields,
        )


def _json_text(value: dict | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for key, item in value.items():
        parts.append(str(key))
        if isinstance(item, dict):
            parts.append(_json_text(item))
        elif isinstance(item, list):
            parts.extend(str(entry) for entry in item)
        elif item is not None:
            parts.append(str(item))
    return " ".join(parts)
