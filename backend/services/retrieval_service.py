from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.citations import build_snippet, distance_to_score
from backend.ai.embedding_client import EmbeddingClientFactory, EmbeddingClientProtocol
from backend.core.security import AuthContext
from backend.db.repo.document import DocumentChunkRepository
from backend.schemas.chat_schema import ChatSource


@dataclass(slots=True)
class RetrievalResult:
    sources: list[ChatSource]
    query_embedding: list[float]


class RetrievalService:
    def __init__(
        self,
        session: AsyncSession,
        embedding_client: EmbeddingClientProtocol | None = None,
    ) -> None:
        self.session = session
        self.embedding_client = embedding_client or EmbeddingClientFactory.create()
        self.chunk_repo = DocumentChunkRepository(session)

    async def retrieve(
        self,
        *,
        question: str,
        auth: AuthContext,
        top_k: int = 6,
        document_ids: list[UUID] | None = None,
    ) -> RetrievalResult:
        query_embedding = await self.embedding_client.embed_query(question)
        rows = await self.chunk_repo.semantic_search(
            embedding=query_embedding,
            auth=auth,
            limit=top_k,
            document_ids=document_ids,
        )

        sources: list[ChatSource] = []
        for chunk, distance in rows:
            document = chunk.document
            if document is None or document.is_deleted:
                continue
            sources.append(
                ChatSource(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    file_name=document.file_name,
                    file_path=document.file_path,
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    snippet=build_snippet(chunk.content),
                    distance=distance,
                    score=distance_to_score(distance),
                )
            )
        return RetrievalResult(sources=sources, query_embedding=query_embedding)
