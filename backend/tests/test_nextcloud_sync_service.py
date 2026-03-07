from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.connectors.nextcloud.schemas import AccessControlEntry, DavNode
from backend.connectors.nextcloud.sync import NextcloudSyncService
from backend.db.models import Connector, Document
from backend.services.nextcloud_sync_service import NextcloudConnectorSyncService


@pytest.mark.asyncio
async def test_upsert_document_preserves_previous_version_tag_for_reindex_checks() -> None:
    document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="file-1",
        file_path="/docs/policy.md",
        file_name="policy.md",
        version_tag="etag-old",
        parse_status="indexed",
        indexed_at=datetime.now(timezone.utc),
        allowed_user_ids=[],
        allowed_group_ids=[],
    )
    connector = Connector(
        id=document.connector_id,
        display_name="Primary Nextcloud",
        base_url="https://nextcloud.example.com",
        username="service-account",
        encrypted_secret="encrypted",
        root_path="/",
    )
    item = SimpleNamespace(
        node=DavNode(
            path="/docs/policy.md",
            href="/remote.php/dav/files/service-account/docs/policy.md",
            file_id="file-1",
            etag="etag-new",
            content_type="text/markdown",
        ),
        acl=AccessControlEntry(
            path="/docs/policy.md",
            owner_user_id="service-account",
            allowed_user_ids=["service-account"],
        ),
    )
    service = NextcloudConnectorSyncService(session=SimpleNamespace())
    service.document_repo = SimpleNamespace(
        get_by_connector_and_external_id=lambda *args: _return_document(document),
        add=lambda *args, **kwargs: _unexpected_add(),
    )

    updated_document, previous_version_tag = await service._upsert_document(
        connector, item
    )

    assert updated_document is document
    assert previous_version_tag == "etag-old"
    assert updated_document.version_tag == "etag-new"
    assert NextcloudConnectorSyncService._document_needs_reindex(
        updated_document, previous_version_tag, item.node.etag
    )


@pytest.mark.asyncio
async def test_snapshot_uses_connector_username_as_default_owner() -> None:
    client = SimpleNamespace(config=SimpleNamespace(username="service-account"))
    calls: list[tuple[str, str | None]] = []

    class FakePermissions:
        async def build_acl_for_path(
            self, remote_path: str, owner_user_id: str | None = None
        ) -> AccessControlEntry:
            calls.append((remote_path, owner_user_id))
            return AccessControlEntry(
                path=remote_path,
                owner_user_id=owner_user_id,
                allowed_user_ids=[owner_user_id] if owner_user_id else [],
            )

    service = NextcloudSyncService(client=client, permissions=FakePermissions())
    service._walk = lambda root_path: _yield_nodes()  # type: ignore[method-assign]

    items = await service.snapshot("/")

    assert len(items) == 1
    assert items[0].acl.owner_user_id == "service-account"
    assert calls == [("/docs/plan.md", "service-account")]


async def _return_document(document: Document) -> Document:
    return document


async def _unexpected_add() -> None:
    raise AssertionError("add should not be called for existing documents")


async def _yield_nodes():
    yield DavNode(
        path="/docs/plan.md",
        href="/remote.php/dav/files/service-account/docs/plan.md",
        file_id="plan-1",
        etag="etag-1",
        content_type="text/markdown",
    )
