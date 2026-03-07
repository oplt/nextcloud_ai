from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.repo.audit_log import AuditLogRepository
from backend.db.repo.chat import ChatMessageRepository, ChatSessionRepository
from backend.db.repo.connector import ConnectorRepository
from backend.db.repo.document import DocumentChunkRepository, DocumentRepository
from backend.db.repo.sync_job import SyncJobRepository
from backend.db.repo.user import RoleRepository, UserRepository


class UnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.roles = RoleRepository(session)
        self.connectors = ConnectorRepository(session)
        self.documents = DocumentRepository(session)
        self.document_chunks = DocumentChunkRepository(session)
        self.chat_sessions = ChatSessionRepository(session)
        self.chat_messages = ChatMessageRepository(session)
        self.sync_jobs = SyncJobRepository(session)
        self.audit_logs = AuditLogRepository(session)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def flush(self) -> None:
        await self.session.flush()
