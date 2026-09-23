from __future__ import annotations

import base64
import hashlib
import logging
import mimetypes
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..connectors.nextcloud.client import AsyncNextcloudClient
from ..core import observability
from ..core.config import settings
from ..core.exceptions import NotFoundError
from ..db.models import Document, DocumentChunk
from ..db.repo.document import DocumentChunkRepository, DocumentRepository
from ..db.repo.outbox import WorkOutboxRepository
from ..ingestion.index_versions import (
    StaleIndexGenerationError,
    begin_index_attempt,
    mark_published,
)
from ..ingestion.pipeline import IngestionPipeline, SEARCHABLE_PARSE_STATUSES
from ..parsers.document_parser import (
    ParsedDocument,
    UnsupportedDocumentTypeError,
    parse_document_bytes,
)
from .connector_service import ConnectorService
from .product_intelligence_service import ProductIntelligenceService

logger = logging.getLogger(__name__)

TOPIC_DOCUMENT_INTELLIGENCE = "document_intelligence"


class DocumentIngestionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.document_repo = DocumentRepository(session)
        self.chunk_repo = DocumentChunkRepository(session)
        self.connector_service = ConnectorService(session)
        self.pipeline = IngestionPipeline(session)
        self.intelligence = ProductIntelligenceService(session)
        self.outbox = WorkOutboxRepository(session)

    async def resolve_document_payload(self, document: Document) -> bytes:
        metadata = dict(document.metadata_json or {})
        stored_payload_b64 = metadata.get("stored_payload_b64")
        if isinstance(stored_payload_b64, str) and stored_payload_b64:
            return base64.b64decode(stored_payload_b64)

        connector = await self.connector_service.get_connector(
            str(document.connector_id)
        )
        if connector.connector_type != "nextcloud":
            raise NotFoundError(
                "Original payload is not available for this document; resync the connector first"
            )

        client = AsyncNextcloudClient(
            self.connector_service.build_nextcloud_config(connector)
        )
        try:
            return await client.download_file(document.file_path)
        finally:
            await client.aclose()

    async def index_document(self, document_id: str) -> Document:
        document = await self.document_repo.get(document_id)
        if document is None:
            raise NotFoundError("Document not found")
        payload = await self.resolve_document_payload(document)
        return await self.ingest_document_bytes(document, payload)

    async def ingest_document_bytes(
        self, document: Document, payload: bytes
    ) -> Document:
        payload_hash = hashlib.sha256(payload).hexdigest()
        expected_version_tag = document.version_tag
        try:
            # Identity check BEFORE mutating published checksum / skipping work.
            if await self._is_current_index_for_payload(document, payload_hash):
                document.ingestion_events_json = [
                    *(document.ingestion_events_json or []),
                    {
                        "stage": "validate_file",
                        "status": "unchanged_current_index",
                        "checksum": payload_hash,
                    },
                ][-50:]
                await self.session.flush()
                return document

            self._apply_file_metadata(
                document=document, payload=payload, payload_hash=payload_hash
            )

            duplicate = await self.document_repo.find_indexed_duplicate(
                checksum=payload_hash,
                source_type=document.source_type or "nextcloud",
                exclude_document_id=document.id,
            )
            if duplicate is not None:
                attempt = await begin_index_attempt(
                    self.session,
                    document,
                    expected_version_tag=expected_version_tag,
                )
                try:
                    await self._clone_index_from_duplicate(
                        source=duplicate,
                        target=document,
                        attempt_generation=attempt.generation,
                    )
                    mark_published(document, attempt)
                except StaleIndexGenerationError:
                    logger.info(
                        "Stale clone skipped document_id=%s generation=%s",
                        document.id,
                        attempt.generation,
                    )
                    return document
                await self.session.flush()
                await self._enqueue_intelligence_outbox(document)
                return document

            parsed = await parse_document_bytes(
                document.file_name, document.mime_type, payload
            )
        except UnsupportedDocumentTypeError as exc:
            await self._mark_unindexed(
                document=document, status="unsupported_type", error_message=str(exc)
            )
            return document

        if self._needs_ocr(parsed):
            document.metadata_json = {
                **dict(document.metadata_json or {}),
                "ingestion_quality": {
                    "parser_backend": parsed.metadata.get("parser"),
                    "text_length": len(parsed.text or ""),
                    "page_count": parsed.metadata.get("page_count")
                    or len(parsed.pages),
                    "table_count": parsed.metadata.get("table_count"),
                    "chunk_count": 0,
                    "embedding_status": "skipped",
                    "embedding_error": None,
                    "indexed_at": None,
                    "needs_ocr": True,
                },
            }
            await self._mark_unindexed(
                document=document,
                status="needs_ocr",
                error_message="No extractable text found; OCR is required before indexing.",
            )
            return document

        attempt = await begin_index_attempt(
            self.session,
            document,
            expected_version_tag=expected_version_tag,
        )
        try:
            await self.pipeline.ingest_document(document, parsed, index_attempt=attempt)
            document.metadata_json = {
                **dict(document.metadata_json or {}),
                **_serializable_parser_metadata(parsed.metadata),
                "indexed_content_checksum": payload_hash,
            }
            mark_published(document, attempt)
        except StaleIndexGenerationError:
            logger.info(
                "Stale ingest publish skipped document_id=%s generation=%s",
                document.id,
                attempt.generation,
            )
            # Prior published generation remains queryable.
            return document
        except Exception as exc:
            # Preserve prior published chunks until a successful replacement.
            document.parse_error = str(exc)
            document.ingestion_events_json = [
                *(document.ingestion_events_json or []),
                {
                    "stage": "finalize_ingestion",
                    "status": "failed_transient",
                    "error": str(exc),
                    "preserved_published_generation": document.published_generation,
                },
            ][-50:]
            await self.session.flush()
            raise

        await self.session.flush()
        await self._enqueue_intelligence_outbox(document, parsed=parsed)
        return document

    async def recompute_product_intelligence(self, document_id: str) -> None:
        if not settings.PRODUCT_INTELLIGENCE_ENABLED:
            return
        if settings.PRODUCT_INTELLIGENCE_EXTRACTION_MODE == "off":
            return
        document = await self.document_repo.get(document_id)
        if document is None:
            raise NotFoundError("Document not found")
        payload = await self.resolve_document_payload(document)
        parsed = await parse_document_bytes(
            document.file_name, document.mime_type, payload
        )
        await self.intelligence.rebuild_document_intelligence(
            document=document, parsed_document=parsed
        )

    async def _is_current_index_for_payload(
        self, document: Document, payload_hash: str
    ) -> bool:
        meta = dict(document.metadata_json or {})
        published_hash = meta.get("indexed_content_checksum") or document.checksum
        if published_hash != payload_hash:
            return False
        if document.parse_status not in SEARCHABLE_PARSE_STATUSES:
            return False
        if document.parse_status == "lexical_ready":
            # Lexical-only is current if text chunks exist.
            return (await self.document_repo.count_chunks(document.id)) > 0
        return not await self.document_repo.has_unusable_chunks(document.id)

    async def _clone_index_from_duplicate(
        self,
        *,
        source: Document,
        target: Document,
        attempt_generation: int,
    ) -> None:
        """Copy immutable chunk artifacts onto target with target provenance/ACLs."""
        from ..ingestion.index_versions import IndexAttempt, assert_publish_allowed

        assert_publish_allowed(
            target,
            IndexAttempt(document_id=str(target.id), generation=attempt_generation),
        )
        source_chunks = await self.chunk_repo.list_by_document(source.id)
        clones: list[DocumentChunk] = []
        for chunk in source_chunks:
            clones.append(
                DocumentChunk(
                    document_id=target.id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    heading_path=chunk.heading_path,
                    content_hash=chunk.content_hash,
                    embedding=chunk.embedding,
                    chunk_type=chunk.chunk_type,
                    embedding_status=chunk.embedding_status,
                    embedding_model=chunk.embedding_model,
                    metadata_json={
                        **dict(chunk.metadata_json or {}),
                        "cloned_from_document_id": str(source.id),
                        "document_id": str(target.id),
                    },
                )
            )
        await self.chunk_repo.replace_for_document(
            target.id, clones, touch_parse_status=False
        )
        target.parse_status = source.parse_status
        target.parse_error = source.parse_error
        target.indexed_at = source.indexed_at
        target.document_type = source.document_type
        target.document_type_confidence = source.document_type_confidence
        target.document_type_reason = source.document_type_reason
        target.document_type_source = source.document_type_source
        target.business_domain = source.business_domain
        target.business_domain_confidence = source.business_domain_confidence
        target.business_domain_reason = source.business_domain_reason
        target.business_domain_source = source.business_domain_source
        target.intelligence_json = source.intelligence_json
        target.page_count = source.page_count
        target.word_count = source.word_count
        target.token_count = source.token_count
        target.language = source.language
        target.metadata_json = {
            **dict(target.metadata_json or {}),
            "indexed_content_checksum": target.checksum,
            "cloned_from_document_id": str(source.id),
            "ingestion_quality": dict(
                (source.metadata_json or {}).get("ingestion_quality") or {}
            ),
        }
        target.ingestion_events_json = [
            *(target.ingestion_events_json or []),
            {
                "stage": "validate_file",
                "status": "cloned_from_duplicate",
                "duplicate_document_id": str(source.id),
                "checksum": target.checksum,
            },
        ][-50:]

    async def _enqueue_intelligence_outbox(
        self, document: Document, *, parsed: ParsedDocument | None = None
    ) -> None:
        if not settings.PRODUCT_INTELLIGENCE_ENABLED:
            return
        mode = settings.PRODUCT_INTELLIGENCE_EXTRACTION_MODE
        if mode == "off":
            return
        if mode == "inline":
            if parsed is None:
                return
            try:
                await self.intelligence.rebuild_document_intelligence(
                    document=document, parsed_document=parsed
                )
            except Exception:
                observability.record_intelligence_extraction_failure()
                logger.exception(
                    "Product intelligence extraction failed (document_id=%s)",
                    document.id,
                )
            return

        fingerprint = (
            (document.metadata_json or {}).get("indexed_content_checksum")
            or document.checksum
            or document.version_tag
            or "unknown"
        )
        generation = int(document.published_generation or 0)
        await self.outbox.enqueue(
            topic=TOPIC_DOCUMENT_INTELLIGENCE,
            payload={
                "document_id": str(document.id),
                "published_generation": generation,
                "indexed_content_checksum": fingerprint,
            },
            idempotency_key=(
                f"document_intelligence:v1:{document.id}:{generation}:{fingerprint}"
            ),
        )

    async def _mark_unindexed(
        self, *, document: Document, status: str, error_message: str
    ) -> None:
        await self.chunk_repo.delete_for_document(document.id)
        await self.intelligence.clear_document_intelligence(document.id)
        metadata = dict(document.metadata_json or {})
        metadata.setdefault(
            "ingestion_quality",
            {
                "parser_backend": None,
                "text_length": 0,
                "page_count": None,
                "table_count": None,
                "chunk_count": 0,
                "embedding_status": "skipped",
                "embedding_error": error_message if status == "failed" else None,
                "indexed_at": None,
                "needs_ocr": status == "needs_ocr",
            },
        )
        metadata.pop("indexed_content_checksum", None)
        document.metadata_json = metadata
        document.parse_status = status
        document.parse_error = error_message
        document.indexed_at = None
        document.ingestion_events_json = [
            *(document.ingestion_events_json or []),
            {"stage": "finalize_ingestion", "status": status, "error": error_message},
        ][-50:]
        await self.session.flush()

    @staticmethod
    def _apply_file_metadata(
        *, document: Document, payload: bytes, payload_hash: str
    ) -> None:
        document.size_bytes = len(payload)
        document.checksum = payload_hash
        document.file_extension = Path(document.file_name).suffix.lower() or None
        document.mime_type = (
            document.mime_type or mimetypes.guess_type(document.file_name)[0]
        )
        document.source_type = document.source_type or "nextcloud"
        document.ingestion_events_json = [
            *(document.ingestion_events_json or []),
            {
                "stage": "validate_file",
                "status": "accepted",
                "checksum": document.checksum,
                "size_bytes": document.size_bytes,
            },
        ][-50:]

    @staticmethod
    def _needs_ocr(parsed: ParsedDocument) -> bool:
        if parsed.metadata.get("parser") == "image-metadata-fallback":
            return True
        if parsed.metadata.get("parser") == "pdfplumber" and not parsed.text.strip():
            return True
        return False


def _serializable_parser_metadata(metadata: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in metadata.items() if key != "attachments"}
