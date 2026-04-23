from __future__ import annotations

import base64
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from backend.connectors.nextcloud.client import AsyncNextcloudClient
from backend.core import observability
from backend.core.config import settings
from backend.core.exceptions import NotFoundError
from backend.db.models import Document
from backend.db.repo.document import DocumentChunkRepository, DocumentRepository
from backend.ingestion.pipeline import IngestionPipeline
from backend.parsers.document_parser import (
    ParsedDocument,
    UnsupportedDocumentTypeError,
    parse_document_bytes,
)
from backend.services.connector_service import ConnectorService
from backend.services.product_intelligence_service import ProductIntelligenceService

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
            parsed = await parse_document_bytes(
                document.file_name, document.mime_type, payload
            )
        except UnsupportedDocumentTypeError as exc:
            await self._mark_unindexed(
                document=document, status="unsupported", error_message=str(exc)
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
            from backend.workers.indexing_tasks import enqueue_document_intelligence

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
        document.parse_status = status
        document.parse_error = error_message
        document.indexed_at = None
        await self.session.flush()


def _serializable_parser_metadata(metadata: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in metadata.items() if key != "attachments"}
