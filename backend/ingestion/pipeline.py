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


EMBEDDING_BATCH_SIZE = 32
MIN_TEXT_LENGTH_FOR_INDEXING = 40


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
        started_at = datetime.now(timezone.utc)
        text = parsed_document.text or ""
        text_length = len(text)

        document.parse_status = "parsing"
        document.file_extension = Path(document.file_name or "").suffix.lower() or None
        document.source_type = document.source_type or "nextcloud"
        document.permission_scope = _permission_scope(document)
        document.page_count = _page_count(parsed_document)
        document.word_count = len(re.findall(r"\S+", text))
        document.token_count = document.word_count
        document.language = document.language or parsed_document.metadata.get("language") or "unknown"

        needs_ocr = _needs_ocr(parsed_document, text_length)
        if text_length < MIN_TEXT_LENGTH_FOR_INDEXING:
            document.parse_status = "needs_ocr" if needs_ocr else "partially_parsed"
            document.parse_error = "Extracted text is too short for reliable classification/indexing."
            document.metadata_json = _with_ingestion_quality(
                document.metadata_json,
                parsed_document=parsed_document,
                text_length=text_length,
                chunk_count=0,
                embedding_status="skipped",
                embedding_error=None,
                indexed_at=None,
                needs_ocr=needs_ocr,
                started_at=started_at,
            )
            document.ingestion_events_json = _append_event(
                document.ingestion_events_json,
                stage="parse_validation",
                status=document.parse_status,
                extra={"text_length": text_length, "needs_ocr": needs_ocr},
            )
            await self.chunk_repo.replace_for_document(document.id, [])
            return []

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
        document.intelligence_json = {
            **intelligence.as_payload(),
            "counts": intelligence.counts(),
        }

        drafts = chunk_parsed_document(parsed_document, chunk_size=850, overlap=100)
        contents = [draft.content for draft in drafts if draft.content and draft.content.strip()]
        embedding_inputs = [_embedding_input(content) for content in contents]

        embeddings: list[list[float] | None] = []
        embedding_status = "skipped"
        embedding_error: str | None = None

        if contents:
            try:
                embeddings = await _embed_in_batches(
                    self.embedding_client,
                    embedding_inputs,
                    batch_size=EMBEDDING_BATCH_SIZE,
                )
                embedding_status = "embedded"
            except Exception as exc:
                embedding_error = str(exc)
                embedding_status = "failed"
                # Keep searchable text chunks even if vector embedding fails.
                embeddings = [None] * len(contents)

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
                    base_metadata={
                        **draft.metadata,
                        "document_type": document.document_type,
                        "business_domain": document.business_domain,
                        "classification_confidence": document.document_type_confidence,
                    },
                ),
            )
            for index, draft in enumerate(drafts)
        ]

        await self.chunk_repo.replace_for_document(document.id, chunks)

        document.parse_status = "indexed" if embedding_status != "failed" else "partially_parsed"
        document.parse_error = embedding_error
        document.indexed_at = datetime.now(timezone.utc)
        document.metadata_json = _with_ingestion_quality(
            document.metadata_json,
            parsed_document=parsed_document,
            text_length=text_length,
            chunk_count=len(chunks),
            embedding_status=embedding_status,
            embedding_error=embedding_error,
            indexed_at=document.indexed_at,
            needs_ocr=needs_ocr,
            started_at=started_at,
        )
        document.ingestion_events_json = _append_event(
            document.ingestion_events_json,
            stage="finalize_ingestion",
            status=document.parse_status,
            extra={
                "chunk_count": len(chunks),
                "embedding_status": embedding_status,
                "classification": document.document_type,
                "business_domain": document.business_domain,
            },
        )
        return chunks


async def _embed_in_batches(
        embedding_client: EmbeddingClientProtocol,
        contents: list[str],
        *,
        batch_size: int,
) -> list[list[float] | None]:
    embeddings: list[list[float] | None] = []
    for start in range(0, len(contents), batch_size):
        batch = contents[start : start + batch_size]
        batch_embeddings = await embedding_client.embed_documents(batch)
        if len(batch_embeddings) != len(batch):
            raise RuntimeError(
                f"Embedding count mismatch: expected {len(batch)}, got {len(batch_embeddings)}"
            )
        embeddings.extend(batch_embeddings)
    return embeddings


def _permission_scope(document: Document) -> str:
    if document.public_link_enabled:
        return "public_link"
    if document.allowed_group_ids:
        return "group"
    if document.allowed_user_ids or document.owner_external_id:
        return "private"
    return "connector"


def _page_count(parsed_document: ParsedDocument) -> int | None:
    return _int_metadata(parsed_document.metadata, "page_count") or (
        len(parsed_document.pages) if parsed_document.pages else None
    )


def _needs_ocr(parsed_document: ParsedDocument, text_length: int) -> bool:
    page_count = _page_count(parsed_document) or 0
    parser_hint = str(parsed_document.metadata.get("parser") or "").lower()
    if parsed_document.metadata.get("needs_ocr") is True:
        return True
    if "ocr" in parser_hint:
        return False
    return page_count > 0 and text_length < max(80, page_count * 25)


def _int_metadata(metadata: dict[str, object], key: str) -> int | None:
    value = metadata.get(key)
    return value if isinstance(value, int) else None


def _chunk_type(metadata: dict[str, object]) -> str:
    if metadata.get("table_line_count"):
        return "table"
    if metadata.get("image_ocr"):
        return "image_ocr"
    return "text"


def _embedding_input(content: str) -> str:
    return re.sub(r"\b[\w.+-]+@[\w.-]+\.\w+\b", " email-address ", content)


def _append_event(
        existing: list[dict] | None,
        *,
        stage: str,
        status: str,
        extra: dict[str, object] | None = None,
) -> list[dict]:
    event = {
        "stage": stage,
        "status": status,
        "at": datetime.now(timezone.utc).isoformat(),
        **(extra or {}),
    }
    return [*(existing or []), event][-50:]


def _with_ingestion_quality(
        metadata_json: dict | None,
        *,
        parsed_document: ParsedDocument,
        text_length: int,
        chunk_count: int,
        embedding_status: str,
        embedding_error: str | None,
        indexed_at: datetime | None,
        needs_ocr: bool,
        started_at: datetime,
) -> dict:
    page_count = _page_count(parsed_document)
    quality = {
        "parser_backend": parsed_document.metadata.get("parser"),
        "text_length": text_length,
        "page_count": page_count,
        "table_count": _int_metadata(parsed_document.metadata, "table_count")
                       or sum(1 for page in parsed_document.pages if "|" in page.text),
        "chunk_count": chunk_count,
        "embedding_status": embedding_status,
        "embedding_error": embedding_error,
        "indexed_at": indexed_at.isoformat() if indexed_at else None,
        "started_at": started_at.isoformat(),
        "duration_ms": int(
            ((indexed_at or datetime.now(timezone.utc)) - started_at).total_seconds() * 1000
        ),
        "needs_ocr": needs_ocr,
    }
    return {**dict(metadata_json or {}), "ingestion_quality": quality}