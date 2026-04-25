from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..connectors.email.imap_client import AsyncImapClient, ImapMessagePayload
from ..core.config import settings
from ..db.models import Connector, Document, SyncJob
from ..db.repo.document import DocumentRepository
from ..parsers.document_parser import ParsedAttachment, parse_email_bytes
from .connector_service import ConnectorService
from .indexing_service import DocumentIngestionService
from .job_lifecycle import JobLifecycleService

_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9._-]+")


class EmailConnectorSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.document_repo = DocumentRepository(session)
        self.connector_service = ConnectorService(session)
        self.ingestion = DocumentIngestionService(session)

    async def sync_connector(
        self,
        connector: Connector,
        *,
        full_reindex: bool = False,
        job: SyncJob | None = None,
    ) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        client = AsyncImapClient(self.connector_service.build_imap_config(connector))
        discovered = 0
        indexed = 0
        failed = 0
        attachments_indexed = 0
        failure_details: list[dict[str, str]] = []
        seen_external_ids: list[str] = []

        if job is not None:
            JobLifecycleService.mark_running(job)

        try:
            messages = await client.fetch_messages()
            if job is not None:
                job.progress_total = len(messages)
                job.progress_completed = 0

            for message in messages:
                discovered += 1
                try:
                    email_document, email_parsed, email_previous_version = (
                        await self._upsert_email_document(
                            connector=connector,
                            message=message,
                        )
                    )
                    seen_external_ids.append(email_document.external_id)

                    if full_reindex or self._document_needs_reindex(
                        email_document, email_previous_version, email_document.version_tag
                    ):
                        await self.ingestion.ingest_document_bytes(
                            email_document, message.raw_message
                        )
                        indexed += 1

                    for index, attachment in enumerate(email_parsed.attachments):
                        attachment_document, attachment_previous_version = (
                            await self._upsert_attachment_document(
                                connector=connector,
                                parent_document=email_document,
                                message=message,
                                attachment=attachment,
                                attachment_index=index,
                                email_metadata=email_parsed.metadata,
                            )
                        )
                        seen_external_ids.append(attachment_document.external_id)
                        if full_reindex or self._document_needs_reindex(
                            attachment_document,
                            attachment_previous_version,
                            attachment_document.version_tag,
                        ):
                            await self.ingestion.ingest_document_bytes(
                                attachment_document,
                                attachment.payload,
                            )
                            attachments_indexed += 1

                    email_document.sync_status = "synced"
                    email_document.sync_error = None
                except Exception as exc:
                    failed += 1
                    failure_details.append(
                        {
                            "uid": message.uid,
                            "stage": "email_ingest",
                            "error": str(exc),
                        }
                    )
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
                        "attachments_indexed": attachments_indexed,
                        "failed": failed,
                        "deleted": deleted,
                        "failures": failure_details[:25],
                    },
                )
            await self.session.commit()
            return {
                "discovered": discovered,
                "indexed": indexed,
                "attachments_indexed": attachments_indexed,
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
                        "attachments_indexed": attachments_indexed,
                        "failed": failed,
                        "failures": failure_details[:25],
                    },
                )
            await self.session.commit()
            raise
        finally:
            await client.aclose()

    async def _upsert_email_document(
        self,
        *,
        connector: Connector,
        message: ImapMessagePayload,
    ) -> tuple[Document, object, str | None]:
        parsed = parse_email_bytes(message.raw_message)
        message_id = str(parsed.metadata.get("message_id") or "").strip()
        external_id = message_id or f"imap:{message.uid}"
        checksum = hashlib.sha256(message.raw_message).hexdigest()
        document = await self.document_repo.get_by_connector_and_external_id(
            connector.id, external_id
        )
        previous_version_tag: str | None = None
        if document is None:
            document = Document(
                connector_id=connector.id,
                external_id=external_id,
                file_path=self._message_file_path(connector.root_path, parsed.metadata, message.uid),
                file_name=self._email_file_name(parsed.metadata, message.uid),
                allowed_user_ids=self._allowed_user_ids(connector),
                allowed_group_ids=[],
                public_link_enabled=False,
            )
            await self.document_repo.add(document, flush=True)
        else:
            previous_version_tag = document.version_tag

        document.file_path = self._message_file_path(
            connector.root_path, parsed.metadata, message.uid
        )
        document.file_name = self._email_file_name(parsed.metadata, message.uid)
        document.mime_type = "message/rfc822"
        document.checksum = checksum
        document.size_bytes = len(message.raw_message)
        document.version_tag = checksum
        document.source_url = (
            f"imap://{connector.base_url.rstrip('/')}/{connector.root_path}/{message.uid}"
        )
        document.modified_at = _metadata_datetime(parsed.metadata.get("date"))
        document.sync_status = "synced"
        document.sync_error = None
        document.last_seen_at = datetime.now(timezone.utc)
        document.is_deleted = False
        document.owner_external_id = str(connector.owner_user_id) if connector.owner_user_id else None
        document.allowed_user_ids = self._allowed_user_ids(connector)
        document.allowed_group_ids = []
        document.public_link_enabled = False
        document.acl_json = {
            "connector_owner_user_id": str(connector.owner_user_id)
            if connector.owner_user_id
            else None,
            "scope": "connector-owner",
        }
        document.metadata_json = {
            **_serializable_email_metadata(parsed.metadata),
            **self._inline_payload_metadata(message.raw_message),
            "source_kind": "email_message",
        }
        return document, parsed, previous_version_tag

    async def _upsert_attachment_document(
        self,
        *,
        connector: Connector,
        parent_document: Document,
        message: ImapMessagePayload,
        attachment: ParsedAttachment,
        attachment_index: int,
        email_metadata: dict[str, object],
    ) -> tuple[Document, str | None]:
        external_id = f"{parent_document.external_id}#attachment:{attachment_index}:{attachment.file_name}"
        checksum = hashlib.sha256(attachment.payload).hexdigest()
        document = await self.document_repo.get_by_connector_and_external_id(
            connector.id, external_id
        )
        previous_version_tag: str | None = None
        if document is None:
            document = Document(
                connector_id=connector.id,
                external_id=external_id,
                file_path=self._attachment_file_path(
                    connector.root_path,
                    email_metadata,
                    message.uid,
                    attachment.file_name,
                ),
                file_name=attachment.file_name,
                allowed_user_ids=self._allowed_user_ids(connector),
                allowed_group_ids=[],
                public_link_enabled=False,
            )
            await self.document_repo.add(document, flush=True)
        else:
            previous_version_tag = document.version_tag

        document.file_path = self._attachment_file_path(
            connector.root_path,
            email_metadata,
            message.uid,
            attachment.file_name,
        )
        document.file_name = attachment.file_name
        document.mime_type = attachment.mime_type
        document.checksum = checksum
        document.size_bytes = len(attachment.payload)
        document.version_tag = checksum
        document.source_url = (
            f"imap://{connector.base_url.rstrip('/')}/{connector.root_path}/{message.uid}/{attachment.file_name}"
        )
        document.modified_at = parent_document.modified_at
        document.sync_status = "synced"
        document.sync_error = None
        document.last_seen_at = datetime.now(timezone.utc)
        document.is_deleted = False
        document.owner_external_id = parent_document.owner_external_id
        document.allowed_user_ids = self._allowed_user_ids(connector)
        document.allowed_group_ids = []
        document.public_link_enabled = False
        document.acl_json = parent_document.acl_json
        document.metadata_json = {
            **_serializable_email_metadata(email_metadata),
            **self._inline_payload_metadata(attachment.payload),
            "source_kind": "email_attachment",
            "email_parent_external_id": parent_document.external_id,
            "email_parent_document_id": str(parent_document.id),
        }
        return document, previous_version_tag

    @staticmethod
    def _document_needs_reindex(
        document: Document, previous_version_tag: str | None, new_version_tag: str | None
    ) -> bool:
        if document.indexed_at is None:
            return True
        if document.parse_status in {"failed", "pending", "unsupported", "unsupported_type", "needs_ocr"}:
            return True
        return previous_version_tag != new_version_tag

    @staticmethod
    def _message_file_path(
        mailbox: str, metadata: dict[str, object], uid: str
    ) -> str:
        thread_key = _sanitize_path_component(str(metadata.get("thread_key") or uid))
        file_name = _sanitize_path_component(
            str(metadata.get("subject") or f"message-{uid}")
        )
        return f"/{mailbox.strip('/')}/{thread_key}/{file_name or f'message-{uid}'}.eml"

    @staticmethod
    def _attachment_file_path(
        mailbox: str,
        metadata: dict[str, object],
        uid: str,
        file_name: str,
    ) -> str:
        thread_key = _sanitize_path_component(str(metadata.get("thread_key") or uid))
        safe_name = _sanitize_path_component(file_name) or f"attachment-{uid}"
        return f"/{mailbox.strip('/')}/{thread_key}/attachments/{safe_name}"

    @staticmethod
    def _email_file_name(metadata: dict[str, object], uid: str) -> str:
        subject = _sanitize_path_component(str(metadata.get("subject") or ""))
        return f"{subject or f'message-{uid}'}.eml"

    @staticmethod
    def _allowed_user_ids(connector: Connector) -> list[str]:
        return [str(connector.owner_user_id)] if connector.owner_user_id else []

    @staticmethod
    def _inline_payload_metadata(payload: bytes) -> dict[str, object]:
        if len(payload) > settings.EMAIL_INLINE_BLOB_MAX_BYTES:
            return {
                "stored_payload_inline": False,
                "stored_payload_size_bytes": len(payload),
            }
        return {
            "stored_payload_inline": True,
            "stored_payload_size_bytes": len(payload),
            "stored_payload_b64": base64.b64encode(payload).decode("ascii"),
        }


def _sanitize_path_component(value: str) -> str:
    return _SANITIZE_RE.sub("-", value.strip()).strip("-.")[:80]


def _serializable_email_metadata(metadata: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in metadata.items()
        if key != "attachments"
    }


def _metadata_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None
