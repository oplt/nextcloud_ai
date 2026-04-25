from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..connectors.nextcloud.client import AsyncNextcloudClient
from ..connectors.nextcloud.permissions import NextcloudPermissionService
from ..connectors.nextcloud.sync import NextcloudSyncService
from ..core.config import settings
from ..db.models import Connector, Document, SyncJob
from ..db.repo.connector import ConnectorRepository
from ..db.repo.document import DocumentRepository
from ..db.session import AsyncSessionLocal
from .job_lifecycle import JobLifecycleService
from .audit_service import AuditService
from .connector_service import ConnectorService
from .indexing_service import DocumentIngestionService

logger = logging.getLogger(__name__)


class NextcloudConnectorSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.connector_repo = ConnectorRepository(session)
        self.document_repo = DocumentRepository(session)
        self.connector_service = ConnectorService(session)
        self.audit = AuditService(session)
        self.ingestion = DocumentIngestionService(session)
        self.session_factory = AsyncSessionLocal

    async def sync_connector(
            self,
            connector: Connector,
            *,
            full_reindex: bool = False,
            job: SyncJob | None = None,
    ) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        config = self.connector_service.build_nextcloud_config(connector)
        client = AsyncNextcloudClient(config)
        permissions = NextcloudPermissionService(client)
        sync_service = NextcloudSyncService(client, permissions)

        discovered = 0
        indexed = 0
        failed = 0
        failure_details: list[dict[str, str]] = []
        seen_external_ids: list[str] = []

        if job is not None:
            JobLifecycleService.mark_running(job)

        try:
            items = await sync_service.snapshot(connector.root_path)
            if job is not None:
                job.progress_total = len(items)
                job.progress_completed = 0
            await self.session.commit()

            for item in items:
                external_id = item.node.file_id or item.node.path
                seen_external_ids.append(external_id)

            concurrency = max(1, settings.NEXTCLOUD_SYNC_INGEST_CONCURRENCY)
            semaphore = asyncio.Semaphore(concurrency)
            progress_lock = asyncio.Lock()

            async def process(item) -> dict:
                async with semaphore:
                    return await self._process_item(
                        connector_id=connector.id,
                        item=item,
                        sync_service=sync_service,
                        full_reindex=full_reindex,
                    )

            async def run_with_progress(item) -> dict:
                outcome = await process(item)
                async with progress_lock:
                    nonlocal discovered
                    discovered += 1
                    if job is not None:
                        JobLifecycleService.advance(job, discovered)
                        await self.session.commit()
                return outcome

            results = await asyncio.gather(
                *(run_with_progress(item) for item in items),
                return_exceptions=False,
            )

            for outcome in results:
                if outcome["status"] == "indexed":
                    indexed += 1
                elif outcome["status"] == "skipped":
                    pass
                else:
                    failed += 1
                    failure_details.append(outcome["failure"])

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
                        "failures": failure_details[:25],
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
                JobLifecycleService.mark_failed(
                    job,
                    str(exc),
                    result={
                        "discovered": discovered,
                        "indexed": indexed,
                        "failed": failed,
                        "failures": failure_details[:25],
                    },
                )
            await self.session.commit()
            raise
        finally:
            await client.aclose()

    async def _process_item(
        self,
        *,
        connector_id,
        item,
        sync_service: NextcloudSyncService,
        full_reindex: bool,
    ) -> dict:
        external_id = item.node.file_id or item.node.path
        try:
            async with self.session_factory() as task_session:
                connector_repo = ConnectorRepository(task_session)
                document_repo = DocumentRepository(task_session)
                ingestion = DocumentIngestionService(task_session)
                connector = await connector_repo.get(connector_id)
                if connector is None:
                    raise RuntimeError(f"Connector {connector_id} disappeared")

                document, previous_version_tag = await self._upsert_document(
                    connector=connector,
                    document_repo=document_repo,
                    item=item,
                )
                should_reindex = full_reindex or self._document_needs_reindex(
                    document, previous_version_tag, item.node.etag
                )
                if not should_reindex:
                    await task_session.commit()
                    return {"status": "skipped"}

                try:
                    payload = await sync_service.fetch_file_bytes(item.node.path)
                    await ingestion.ingest_document_bytes(document, payload)
                    document.sync_status = "synced"
                    document.sync_error = None
                    await task_session.commit()
                    return {"status": "indexed"}
                except Exception as exc:
                    error_message = str(exc)
                    document.sync_status = "error"
                    document.sync_error = error_message
                    document.parse_status = "failed"
                    document.parse_error = error_message
                    await task_session.commit()
                    return {
                        "status": "failed",
                        "failure": {
                            "document_id": str(document.id),
                            "external_id": external_id,
                            "file_path": item.node.path,
                            "stage": "ingest",
                            "error": error_message,
                        },
                    }
        except Exception as exc:
            logger.exception(
                "Sync upsert failed external_id=%s path=%s",
                external_id,
                item.node.path,
            )
            return {
                "status": "failed",
                "failure": {
                    "external_id": external_id,
                    "file_path": item.node.path,
                    "stage": "upsert",
                    "error": str(exc),
                },
            }

    async def _upsert_document(
            self,
            *,
            connector: Connector,
            document_repo: DocumentRepository,
            item,
    ) -> tuple[Document, str | None]:
        external_id = item.node.file_id or item.node.path
        document = await document_repo.get_by_connector_and_external_id(
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
            await document_repo.add(document, flush=True)
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
        if document.parse_status in {"failed", "pending", "unsupported", "unsupported_type", "needs_ocr"}:
            return True
        return previous_version_tag != new_etag
