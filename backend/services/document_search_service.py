from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security import AuthContext
from ..db.models import Document
from ..db.repo.document import DocumentRepository
from ..rag.lexical import classify_catalog_intent, semantic_json_text
from ..rag.scope import RetrievalScope
from ..schemas.chat_schema import RetrievalFilters

_DISCOVERY_RE = re.compile(
    r"\b(find|show|list|search|locate|get)\b", flags=re.IGNORECASE
)
_TOKEN_RE = re.compile(r"[^\W\s]+(?:[-./_][^\W\s]+)*", flags=re.UNICODE)
_FILE_REFERENCE_RE = re.compile(
    r"\b[^\W\s][\w._-]{1,180}\.(?:pdf|docx?|xlsx?|pptx?|txt|csv|md|eml|od[pts])\b",
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
    matched_excerpt: str | None = None

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
            "matched_excerpt": self.matched_excerpt,
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
        scope = RetrievalScope.resolve(auth=auth, filters=filters)
        ranked = await self.repo.search_documents(
            auth=scope.auth,
            terms=terms,
            **scope.repository_filters(),
            limit=limit,
        )
        results = [
            self._score_document(
                document,
                terms,
                lexical_rank=rank,
                matched_excerpt=matched_excerpt,
            )
            for document, rank, matched_excerpt in ranked
        ]
        results.sort(key=lambda item: item.score, reverse=True)
        return [item for item in results if item.score > 0]

    async def count(
        self,
        *,
        query: str,
        auth: AuthContext,
        filters: RetrievalFilters | None = None,
    ) -> int:
        terms = self.extract_terms(query)
        if not terms:
            return 0
        scope = RetrievalScope.resolve(auth=auth, filters=filters)
        return await self.repo.count_search_documents(
            auth=scope.auth,
            terms=terms,
            **scope.repository_filters(),
        )

    @staticmethod
    def is_document_discovery_query(query: str) -> bool:
        """Navigation only. Factual and exhaustive catalog queries return false."""
        if classify_catalog_intent(query) != "navigation":
            return False
        lowered = query.lower()
        return bool(_DISCOVERY_RE.search(lowered)) and any(
            token not in _STOPWORDS for token in _TOKEN_RE.findall(lowered)
        )

    @staticmethod
    def is_exhaustive_catalog_query(query: str) -> bool:
        return classify_catalog_intent(query) == "exhaustive"

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
        self,
        document: Document,
        terms: list[str],
        *,
        lexical_rank: float = 0.0,
        matched_excerpt: str | None = None,
    ) -> DocumentSearchResult:
        fields = {
            "file_name": document.file_name,
            "file_path": document.file_path,
            "document_type": document.document_type,
            "business_domain": document.business_domain,
            "metadata_json": semantic_json_text(document.metadata_json),
            "extracted_fields_json": semantic_json_text(document.extracted_fields_json),
        }
        weights = {
            "file_name": 1.0,
            "file_path": 0.8,
            "document_type": 1.2,
            "business_domain": 0.8,
            "metadata_json": 0.7,
            "extracted_fields_json": 1.4,
        }
        matched_fields: list[str] = []
        raw_score = 0.0
        for field, value in fields.items():
            haystack = (value or "").lower()
            hits = sum(1 for term in terms if term in haystack)
            if hits:
                matched_fields.append(field)
                raw_score += weights[field] * hits / max(len(terms), 1)
        if lexical_rank > 0:
            matched_fields.append("content")
            # ts_rank_cd, not a sample of the first chunks.
            raw_score += lexical_rank
        lowered_name = (document.file_name or "").lower()
        lowered_path = (document.file_path or "").lower()
        for term in terms:
            if "." in term and (
                term == lowered_name or lowered_path.endswith(f"/{term}")
            ):
                raw_score += 2.0
                if "file_name" not in matched_fields:
                    matched_fields.append("file_name")
                break
        return DocumentSearchResult(
            document=document,
            score=raw_score,
            matched_fields=matched_fields,
            matched_excerpt=(matched_excerpt[:420] if matched_excerpt else None),
        )
