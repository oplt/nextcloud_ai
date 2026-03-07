from __future__ import annotations

import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.chunker import chunk_text
from backend.ai.ollama_embedding_client import OllamaEmbeddingClient
from backend.models import DocumentChunk
from backend.repositories.document import DocumentChunkRepository


class IngestionPipeline:

    def __init__(
        self,
        session: AsyncSession,
    ):
        self.session = session
        self.embedding_client = OllamaEmbeddingClient()
        self.chunk_repo = DocumentChunkRepository(session)

    async def ingest_document(
        self,
        document_id,
        text: str,
    ):

        chunks = chunk_text(text)

        embeddings = await self.embedding_client.embed_documents(chunks)

        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):

            chunk_hash = hashlib.sha256(chunk.encode()).hexdigest()

            chunk_model = DocumentChunk(
                document_id=document_id,
                chunk_index=i,
                content=chunk,
                token_count=len(chunk.split()),
                embedding=emb,
                content_hash=chunk_hash,
            )

            await self.chunk_repo.add(chunk_model)

        await self.session.commit()