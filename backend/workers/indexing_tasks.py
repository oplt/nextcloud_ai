from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.ingestion.pipeline import IngestionPipeline
from backend.db.models import Document
from backend.parsers.document_parser import parse_docx, parse_pdf, parse_txt
from backend.db.repo.document import DocumentRepository


class IndexingService:

    def __init__(self, session: AsyncSession):
        self.session = session
        self.doc_repo = DocumentRepository(session)
        self.pipeline = IngestionPipeline(session)

    async def index_document(self, document_id):

        document = await self.doc_repo.get(document_id)

        if not document:
            raise ValueError("Document not found")

        path = document.file_path

        if path.endswith(".pdf"):
            text = await parse_pdf(path)

        elif path.endswith(".docx"):
            text = await parse_docx(path)

        elif path.endswith(".txt"):
            text = await parse_txt(path)

        else:
            raise ValueError("Unsupported format")

        await self.pipeline.ingest_document(
            document_id=document.id,
            text=text,
        )

        document.parse_status = "indexed"

        await self.session.commit()