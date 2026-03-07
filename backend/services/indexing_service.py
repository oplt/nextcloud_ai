from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.connectors.nextcloud.client import AsyncNextcloudClient
from backend.core.exceptions import NotFoundError
from backend.db.models import Document
from backend.db.repo.document import DocumentChunkRepository, DocumentRepository
from backend.ingestion.pipeline import IngestionPipeline
from backend.parsers.document_parser import (
    UnsupportedDocumentTypeError,
    parse_document_bytes,
)
from backend.services.connector_service import ConnectorService


class DocumentIngestionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.document_repo = DocumentRepository(session)
        self.chunk_repo = DocumentChunkRepository(session)
        self.connector_service = ConnectorService(session)
        self.pipeline = IngestionPipeline(session)

    async def index_document(self, document_id: str) -> Document:
        document = await self.document_repo.get(document_id)
        if document is None:
            raise NotFoundError("Document not found")
        connector = await self.connector_service.get_connector(
            str(document.connector_id)
        )
        client = AsyncNextcloudClient(self.connector_service.build_config(connector))
        try:
            payload = await client.download_file(document.file_path)
            return await self.ingest_document_bytes(document, payload)
        finally:
            await client.aclose()

    async def ingest_document_bytes(
        self, document: Document, payload: bytes
    ) -> Document:
        try:
            parsed = await parse_document_bytes(
                document.file_name, document.mime_type, payload
            )
            await self.pipeline.ingest_document(document, parsed)
        except UnsupportedDocumentTypeError as exc:
            await self._mark_unindexed(
                document=document, status="unsupported", error_message=str(exc)
            )
            return document
        except Exception as exc:
            await self._mark_unindexed(
                document=document, status="failed", error_message=str(exc)
            )
            raise
        await self.session.flush()
        return document

    async def _mark_unindexed(
        self, *, document: Document, status: str, error_message: str
    ) -> None:
        await self.chunk_repo.delete_for_document(document.id)
        document.parse_status = status
        document.parse_error = error_message
        document.indexed_at = None
        await self.session.flush()
