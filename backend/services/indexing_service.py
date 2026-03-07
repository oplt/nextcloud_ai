from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.connectors.nextcloud.client import AsyncNextcloudClient
from backend.core.exceptions import NotFoundError
from backend.db.models import Document
from backend.db.repo.document import DocumentRepository
from backend.ingestion.pipeline import IngestionPipeline
from backend.parsers.document_parser import UnsupportedDocumentTypeError, parse_document_bytes
from backend.services.connector_service import ConnectorService


class DocumentIngestionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.document_repo = DocumentRepository(session)
        self.connector_service = ConnectorService(session)
        self.pipeline = IngestionPipeline(session)

    async def index_document(self, document_id: str) -> Document:
        document = await self.document_repo.get(document_id)
        if document is None:
            raise NotFoundError("Document not found")
        connector = await self.connector_service.get_connector(str(document.connector_id))
        client = AsyncNextcloudClient(self.connector_service.build_config(connector))
        try:
            payload = await client.download_file(document.file_path)
            return await self.ingest_document_bytes(document, payload)
        finally:
            await client.aclose()

    async def ingest_document_bytes(self, document: Document, payload: bytes) -> Document:
        try:
            parsed = await parse_document_bytes(document.file_name, document.mime_type, payload)
        except UnsupportedDocumentTypeError as exc:
            document.parse_status = "unsupported"
            document.parse_error = str(exc)
            await self.session.flush()
            return document
        except Exception as exc:
            document.parse_status = "failed"
            document.parse_error = str(exc)
            await self.session.flush()
            raise

        await self.pipeline.ingest_document(document, parsed)
        await self.session.flush()
        return document
