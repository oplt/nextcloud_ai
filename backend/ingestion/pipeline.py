from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.chunker import chunk_parsed_document
from backend.ai.embedding_client import EmbeddingClientFactory, EmbeddingClientProtocol
from backend.db.models import Document, DocumentChunk
from backend.db.repo.document import DocumentChunkRepository
from backend.parsers.document_parser import ParsedDocument


class IngestionPipeline:
    def __init__(self, session: AsyncSession, embedding_client: EmbeddingClientProtocol | None = None) -> None:
        self.session = session
        self.embedding_client = embedding_client or EmbeddingClientFactory.create()
        self.chunk_repo = DocumentChunkRepository(session)

    async def ingest_document(self, document: Document, parsed_document: ParsedDocument) -> list[DocumentChunk]:
        drafts = chunk_parsed_document(parsed_document)
        contents = [draft.content for draft in drafts]
        embeddings = await self.embedding_client.embed_documents(contents) if contents else []

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
                metadata_json=draft.metadata,
            )
            for index, draft in enumerate(drafts)
        ]

        await self.chunk_repo.replace_for_document(document.id, chunks)
        document.parse_status = "indexed"
        document.parse_error = None
        document.indexed_at = datetime.now(timezone.utc)
        return chunks
