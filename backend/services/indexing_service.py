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
from ..db.models import Document
from ..db.repo.document import DocumentChunkRepository, DocumentRepository
from ..ingestion.pipeline import IngestionPipeline
from ..parsers.document_parser import (
    ParsedDocument,
    UnsupportedDocumentTypeError,
    parse_document_bytes,
)
from .connector_service import ConnectorService
from .product_intelligence_service import ProductIntelligenceService

logger = logging.getLogger(__name__)


class DocumentIngestionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.document_repo = DocumentRepository(session)
        self.chunk_repo = DocumentChunkRepository(session)
        self.connector_service = ConnectorService(session)
        self.pipeline = IngestionPipeline(session)
        self.intelligence = ProductIntelligenceService(session)

    async def resolve_document_payload(self, document: Document) -> bytes:
        metadata = dict(document.metadata_json or {})
        stored_payload_b64 = metadata.get("stored_payload_b64")
        if isinstance(stored_payload_b64, str) and stored_payload_b64:
            return base64.b64decode(stored_payload_b64)

        connector = await self.connector_service.get_connector(str(document.connector_id))
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
        try:
            self._validate_file_metadata(document=document, payload=payload)
            duplicate = await self.document_repo.find_indexed_duplicate(
                checksum=document.checksum or "",
                source_type=document.source_type,
                exclude_document_id=document.id,
            )
            if duplicate and document.parse_status == "indexed":
                document.ingestion_events_json = [
                    *(document.ingestion_events_json or []),
                    {
                        "stage": "validate_file",
                        "status": "duplicate_unchanged",
                        "duplicate_document_id": str(duplicate.id),
                    },
                ][-50:]
                await self.session.flush()
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
                    "page_count": parsed.metadata.get("page_count") or len(parsed.pages),
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

        try:
            await self.pipeline.ingest_document(document, parsed)
            document.metadata_json = {
                **dict(document.metadata_json or {}),
                **_serializable_parser_metadata(parsed.metadata),
            }
        except Exception as exc:
            await self._mark_unindexed(
                document=document, status="failed", error_message=str(exc)
            )
            raise

        await self.session.flush()
        await self._apply_product_intelligence_after_index(document, parsed)
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

    async def _apply_product_intelligence_after_index(
        self, document: Document, parsed: ParsedDocument
    ) -> None:
        if not settings.PRODUCT_INTELLIGENCE_ENABLED:
            return
        mode = settings.PRODUCT_INTELLIGENCE_EXTRACTION_MODE
        if mode == "off":
            return
        if mode == "async":
            from ..workers.indexing_tasks import enqueue_document_intelligence

            enqueue_document_intelligence(str(document.id))
            return
        try:
            await self.intelligence.rebuild_document_intelligence(
                document=document, parsed_document=parsed
            )
        except Exception:
            observability.record_intelligence_extraction_failure()
            logger.exception(
                "Product intelligence extraction failed (document_id=%s)", document.id
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
    def _validate_file_metadata(*, document: Document, payload: bytes) -> None:
        document.size_bytes = len(payload)
        document.checksum = hashlib.sha256(payload).hexdigest()
        document.file_extension = Path(document.file_name).suffix.lower() or None
        document.mime_type = document.mime_type or mimetypes.guess_type(document.file_name)[0]
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
