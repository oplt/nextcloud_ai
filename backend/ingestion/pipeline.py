from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from sqlalchemy.ext.asyncio import AsyncSession

from ..ai.chunker import chunk_parsed_document
from ..ai.embedding_client import EmbeddingClientFactory, EmbeddingClientProtocol
from ..core.config import settings
from ..db.models import Document, DocumentChunk
from ..db.repo.document import DocumentChunkRepository
from ..parsers.document_parser import ParsedDocument
from ..rag.metadata import build_chunk_metadata
from .classifier import DocumentClassifier
from .intelligence import extract_intelligence


class IngestionPipeline:
    def __init__(
        self,
        session: AsyncSession,
        embedding_client: EmbeddingClientProtocol | None = None,
    ) -> None:
        self.session = session
        self.embedding_client = embedding_client or EmbeddingClientFactory.create()
        self.chunk_repo = DocumentChunkRepository(session)
        self.classifier = DocumentClassifier()

    async def ingest_document(
        self, document: Document, parsed_document: ParsedDocument
    ) -> list[DocumentChunk]:
        document.parse_status = "parsing"
        document.file_extension = Path(document.file_name).suffix.lower() or None
        document.source_type = document.source_type or "nextcloud"
        document.permission_scope = _permission_scope(document)
        document.page_count = _int_metadata(parsed_document.metadata, "page_count") or (
            len(parsed_document.pages) if parsed_document.pages else None
        )
        document.word_count = len(re.findall(r"\S+", parsed_document.text))
        document.token_count = document.word_count
        document.language = document.language or "unknown"
        document.parse_status = "parsed"

        classification = await self.classifier.classify(document=document, parsed=parsed_document)
        document.document_type = classification.document_type
        document.document_type_confidence = classification.document_type_confidence
        document.document_type_reason = classification.document_type_reason
        document.document_type_source = classification.document_type_source
        document.business_domain = classification.business_domain
        document.business_domain_confidence = classification.business_domain_confidence
        document.business_domain_reason = classification.business_domain_reason
        document.business_domain_source = classification.business_domain_source
        document.classified_at = datetime.now(timezone.utc)

        intelligence = extract_intelligence(parsed_document)
        document.intelligence_json = intelligence.as_payload()

        drafts = chunk_parsed_document(parsed_document, chunk_size=700, overlap=120)
        contents = [draft.content for draft in drafts]
        embeddings: list[list[float] | None] = []
        embedding_status = "skipped"
        embedding_error: str | None = None
        if contents:
            try:
                embeddings = await self.embedding_client.embed_documents(contents)
                embedding_status = "embedded"
            except Exception as exc:
                embeddings = [None for _ in contents]
                embedding_status = "failed"
                embedding_error = str(exc)

        chunks = [
            DocumentChunk(
                document_id=document.id,
                chunk_index=draft.chunk_index,
                content=draft.content,
                token_count=draft.token_count,
                char_start=draft.char_start,
                char_end=draft.char_end,
                page_number=draft.page_number,
                section_title=draft.section_title,
                heading_path=draft.heading_path,
                content_hash=draft.content_hash,
                embedding=embeddings[index] if index < len(embeddings) else None,
                chunk_type=_chunk_type(draft.metadata),
                embedding_status=embedding_status if contents else "skipped",
                embedding_model=settings.OLLAMA_EMBEDDING_MODEL if embedding_status == "embedded" else None,
                metadata_json=build_chunk_metadata(
                    document=document,
                    chunk_index=draft.chunk_index,
                    page_number=draft.page_number,
                    section_title=draft.section_title,
                    base_metadata=draft.metadata,
                ),
            )
            for index, draft in enumerate(drafts)
        ]

        await self.chunk_repo.replace_for_document(document.id, chunks)
        document.parse_status = "indexed"
        document.parse_error = embedding_error
        document.indexed_at = datetime.now(timezone.utc)
        document.ingestion_events_json = [
            *(document.ingestion_events_json or []),
            {
                "stage": "finalize_ingestion",
                "status": "indexed",
                "chunk_count": len(chunks),
                "embedding_status": embedding_status,
                "at": document.indexed_at.isoformat(),
            },
        ][-50:]
        return chunks


def _permission_scope(document: Document) -> str:
    if document.public_link_enabled:
        return "public_link"
    if document.allowed_group_ids:
        return "group"
    if document.allowed_user_ids or document.owner_external_id:
        return "private"
    return "connector"


def _int_metadata(metadata: dict[str, object], key: str) -> int | None:
    value = metadata.get(key)
    return value if isinstance(value, int) else None


def _chunk_type(metadata: dict[str, object]) -> str:
    if metadata.get("table_line_count"):
        return "table"
    return "text"
