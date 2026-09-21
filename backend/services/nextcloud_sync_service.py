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
            progress_every = max(1, settings.NEXTCLOUD_SYNC_PROGRESS_EVERY)
            queue: asyncio.Queue[object | None] = asyncio.Queue()
            for item in items:
                queue.put_nowait(item)
            for _ in range(concurrency):
                queue.put_nowait(None)

            progress_lock = asyncio.Lock()
            results: list[dict] = []

            async def worker() -> None:
                nonlocal discovered
                while True:
                    item = await queue.get()
                    if item is None:
                        queue.task_done()
                        return
                    try:
                        # Each item uses its own DB session inside _process_item.
                        outcome = await self._process_item(
                            connector_id=connector.id,
                            item=item,
                            sync_service=sync_service,
                            full_reindex=full_reindex,
                        )
                        async with progress_lock:
                            results.append(outcome)
                            discovered += 1
                            if job is not None and (
                                discovered % progress_every == 0
                                or discovered == len(items)
                            ):
                                JobLifecycleService.advance(job, discovered)
                                await self.session.commit()
                    finally:
                        queue.task_done()

            workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
            await queue.join()
            await asyncio.gather(*workers)

            for outcome in results:
                if outcome["status"] == "indexed":
                    indexed += 1
                elif outcome["status"] in {"skipped", "lexical_only", "non_vector"}:
                    pass
                else:
                    failed += 1
                    if outcome.get("failure"):
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
            # Post-commit outbox drain (broker failure leaves rows for retry).
            try:
                from ..workers.outbox_dispatcher import dispatch_outbox_batch

                await dispatch_outbox_batch()
            except Exception:
                logger.exception("Outbox dispatch after Nextcloud sync failed")
            return {
                "discovered": discovered,
                "indexed": indexed,
                "failed": failed,
                "deleted": deleted,
            }
        except Exception as exc:
            try:
                await self.session.rollback()
            except Exception:
                logger.exception("Rollback failed after Nextcloud sync error")
            async with self.session_factory() as fail_session:
                connector_repo = ConnectorRepository(fail_session)
                failed_connector = await connector_repo.get(connector.id)
                if failed_connector is not None:
                    failed_connector.status = "error"
                    failed_connector.last_error = str(exc)
                if job is not None:
                    from ..db.repo.sync_job import SyncJobRepository

                    failed_job = await SyncJobRepository(fail_session).get(job.id)
                    if failed_job is not None:
                        JobLifecycleService.mark_failed(
                            failed_job,
                            str(exc),
                            result={
                                "discovered": discovered,
                                "indexed": indexed,
                                "failed": failed,
                                "failures": failure_details[:25],
                            },
                        )
                await fail_session.commit()
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
                should_reindex = (
                    full_reindex
                    or self._document_needs_reindex(
                        document, previous_version_tag, item.node.etag
                    )
                    or await self._document_has_unusable_chunks(document, document_repo)
                )
                if not should_reindex:
                    await task_session.commit()
                    return {"status": "skipped"}

                try:
                    payload = await sync_service.fetch_file_bytes(item.node.path)
                    await ingestion.ingest_document_bytes(document, payload)
                    document.sync_status = "synced"
                    document.sync_error = None
                    parse_status = document.parse_status
                    document_id = document.id
                    await task_session.commit()
                    if parse_status == "indexed":
                        return {"status": "indexed"}
                    if parse_status == "lexical_ready":
                        return {"status": "lexical_only"}
                    if parse_status in {
                        "needs_ocr",
                        "unsupported_type",
                        "unsupported",
                        "partially_parsed",
                    }:
                        return {
                            "status": "non_vector",
                            "parse_status": parse_status,
                        }
                    return {"status": "indexed"}
                except Exception as exc:
                    error_message = str(exc)
                    document_id = document.id
                    try:
                        await task_session.rollback()
                    except Exception:
                        logger.exception("Rollback failed after ingest error")
                    async with self.session_factory() as fail_session:
                        fail_repo = DocumentRepository(fail_session)
                        failed_doc = await fail_repo.get(document_id)
                        if failed_doc is not None:
                            failed_doc.sync_status = "error"
                            failed_doc.sync_error = error_message
                            failed_doc.parse_status = "failed"
                            failed_doc.parse_error = error_message
                            await fail_session.commit()
                    return {
                        "status": "failed",
                        "failure": {
                            "document_id": str(document_id),
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
        # ETag is a sync version token, not a content checksum. Content hash is
        # set during ingest from payload bytes.
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
        previous_meta = dict(document.metadata_json or {})
        document.metadata_json = {
            **previous_meta,
            "href": item.node.href,
            "etag": item.node.etag,
        }
        return document, previous_version_tag

    @staticmethod
    def _document_needs_reindex(
        document: Document, previous_version_tag: str | None, new_etag: str | None
    ) -> bool:
        if document.indexed_at is None:
            return True
        if document.parse_status in {
            "failed",
            "pending",
            "partially_parsed",
            "unsupported",
            "unsupported_type",
            "needs_ocr",
        }:
            return True
        return previous_version_tag != new_etag

    @staticmethod
    async def _document_has_unusable_chunks(
        document: Document, document_repo: DocumentRepository
    ) -> bool:
        if document.parse_status != "indexed":
            return False
        return await document_repo.has_unusable_chunks(document.id)
