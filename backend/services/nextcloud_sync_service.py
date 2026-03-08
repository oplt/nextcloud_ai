from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.connectors.nextcloud.client import AsyncNextcloudClient
from backend.connectors.nextcloud.permissions import NextcloudPermissionService
from backend.connectors.nextcloud.sync import NextcloudSyncService
from backend.db.models import Connector, Document, SyncJob
from backend.db.repo.connector import ConnectorRepository
from backend.db.repo.document import DocumentRepository
from backend.services.job_lifecycle import JobLifecycleService
from backend.services.audit_service import AuditService
from backend.services.connector_service import ConnectorService
from backend.services.indexing_service import DocumentIngestionService


class NextcloudConnectorSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.connector_repo = ConnectorRepository(session)
        self.document_repo = DocumentRepository(session)
        self.connector_service = ConnectorService(session)
        self.audit = AuditService(session)
        self.ingestion = DocumentIngestionService(session)

    async def sync_connector(
            self,
            connector: Connector,
            *,
            full_reindex: bool = False,
            job: SyncJob | None = None,
    ) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        config = self.connector_service.build_config(connector)
        client = AsyncNextcloudClient(config)
        permissions = NextcloudPermissionService(client)
        sync_service = NextcloudSyncService(client, permissions)

        discovered = 0
        indexed = 0
        failed = 0
        seen_external_ids: list[str] = []

        if job is not None:
            JobLifecycleService.mark_running(job)

        try:
            items = await sync_service.snapshot(connector.root_path)
            if job is not None:
                job.progress_total = len(items)
                job.progress_completed = 0

            for item in items:
                discovered += 1
                seen_external_ids.append(item.node.file_id or item.node.path)
                document, previous_version_tag = await self._upsert_document(
                    connector, item
                )
                should_reindex = full_reindex or self._document_needs_reindex(
                    document, previous_version_tag, item.node.etag
                )
                if should_reindex:
                    try:
                        payload = await sync_service.fetch_file_bytes(item.node.path)
                        await self.ingestion.ingest_document_bytes(document, payload)
                        indexed += 1
                    except Exception as exc:
                        failed += 1
                        document.parse_status = "failed"
                        document.parse_error = str(exc)
                if job is not None:
                    JobLifecycleService.advance(job, discovered)
                await self.session.flush()

            deleted = await self.document_repo.mark_deleted_missing_from_external_ids(
                connector_id=connector.id,
                external_ids=seen_external_ids,
            )
            connector.last_sync_at = now
            connector.last_error = None
            connector.status = "healthy"
            if job is not None:
                JobLifecycleService.mark_succeeded(
                    job,
                    {
                        "discovered": discovered,
                        "indexed": indexed,
                        "failed": failed,
                        "deleted": deleted,
                    },
                )
            await self.session.commit()
            return {
                "discovered": discovered,
                "indexed": indexed,
                "failed": failed,
                "deleted": deleted,
            }
        except Exception as exc:
            connector.status = "error"
            connector.last_error = str(exc)
            if job is not None:
                JobLifecycleService.mark_failed(job, str(exc))
            await self.session.commit()
            raise
        finally:
            await client.aclose()

    async def _upsert_document(
            self, connector: Connector, item
    ) -> tuple[Document, str | None]:
        external_id = item.node.file_id or item.node.path
        document = await self.document_repo.get_by_connector_and_external_id(
            connector.id, external_id
        )
        previous_version_tag: str | None = None
        if document is None:
            document = Document(
                connector_id=connector.id,
                external_id=external_id,
                file_path=item.node.path,
                file_name=item.node.path.split("/")[-1],
            )
            await self.document_repo.add(document, flush=True)
        else:
            previous_version_tag = document.version_tag

        document.file_path = item.node.path
        document.file_name = item.node.path.split("/")[-1]
        document.mime_type = item.node.content_type
        document.checksum = item.node.etag
        document.size_bytes = item.node.size_bytes
        document.version_tag = item.node.etag
        document.source_url = f"{connector.base_url.rstrip('/')}/f/{external_id}"
        document.modified_at = item.node.last_modified
        document.sync_status = "synced"
        document.sync_error = None
        document.last_seen_at = datetime.now(timezone.utc)
        document.is_deleted = False
        document.owner_external_id = item.acl.owner_user_id
        document.allowed_user_ids = item.acl.allowed_user_ids
        document.allowed_group_ids = item.acl.allowed_group_ids
        document.public_link_enabled = item.acl.public_link_enabled
        document.acl_json = item.acl.model_dump(mode="json")
        document.metadata_json = {"href": item.node.href}
        return document, previous_version_tag

    @staticmethod
    def _document_needs_reindex(
            document: Document, previous_version_tag: str | None, new_etag: str | None
    ) -> bool:
        if document.indexed_at is None:
            return True
        if document.parse_status in {"failed", "pending"}:
            return True
        return previous_version_tag != new_etag