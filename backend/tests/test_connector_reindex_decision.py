from datetime import datetime, timezone
from uuid import uuid4

from backend.db.models import Document
from backend.services.email_sync_service import EmailConnectorSyncService
from backend.services.nextcloud_sync_service import NextcloudConnectorSyncService


def _document(parse_status: str) -> Document:
    return Document(
        id=uuid4(),
        file_name="doc.pdf",
        file_path="/doc.pdf",
        sync_status="synced",
        parse_status=parse_status,
        indexed_at=datetime.now(timezone.utc),
        source_type="nextcloud",
        is_deleted=False,
    )


def test_nextcloud_sync_reindexes_partially_parsed_documents() -> None:
    assert NextcloudConnectorSyncService._document_needs_reindex(
        _document("partially_parsed"),
        previous_version_tag="etag",
        new_etag="etag",
    )


def test_email_sync_reindexes_partially_parsed_documents() -> None:
    assert EmailConnectorSyncService._document_needs_reindex(
        _document("partially_parsed"),
        previous_version_tag="etag",
        new_version_tag="etag",
    )
