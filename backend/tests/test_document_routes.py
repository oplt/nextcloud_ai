from __future__ import annotations

import base64
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.api.v1 import document_routes
from backend.db.models import Connector, Document


def test_build_content_disposition_includes_utf8_filename() -> None:
    header = document_routes.build_content_disposition('Financé "report".pdf')

    assert header.startswith("inline;")
    assert 'filename="' in header
    assert "filename*=UTF-8''Financ%C3%A9%20%22report%22.pdf" in header


@pytest.mark.asyncio
async def test_get_document_original_downloads_file_from_nextcloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="report-1",
        file_path="/docs/report.pdf",
        file_name='report "2025".pdf',
        mime_type="application/pdf",
        parse_status="indexed",
        sync_status="synced",
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
    auth = SimpleNamespace()
    clients: list[FakeNextcloudClient] = []

    async def fake_get_visible_to_auth(self, document_id: str, current_auth: object) -> Document:
        assert document_id == str(document.id)
        assert current_auth is auth
        return document

    async def fake_get_connector(self, connector_id: str) -> Connector:
        assert connector_id == str(connector.id)
        return connector

    class FakeNextcloudClient:
        def __init__(self, config: object) -> None:
            self.config = config
            self.closed = False
            clients.append(self)

        async def download_file(self, remote_path: str) -> bytes:
            assert remote_path == document.file_path
            return b"%PDF-1.7"

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setattr(
        document_routes.DocumentRepository,
        "get_visible_to_auth",
        fake_get_visible_to_auth,
    )
    monkeypatch.setattr(document_routes.ConnectorRepository, "get", fake_get_connector)
    monkeypatch.setattr(
        document_routes.ConnectorService,
        "build_config",
        lambda self, current_connector: SimpleNamespace(connector=current_connector),
    )
    monkeypatch.setattr(document_routes, "AsyncNextcloudClient", FakeNextcloudClient)

    response = await document_routes.get_document_original(
        str(document.id),
        session=SimpleNamespace(),
        identity=SimpleNamespace(auth=auth),
    )

    assert response.body == b"%PDF-1.7"
    assert response.media_type == "application/pdf"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-length"] == "8"
    assert response.headers["content-disposition"].startswith("inline;")
    assert clients and clients[0].closed is True


@pytest.mark.asyncio
async def test_get_document_original_returns_inline_email_payload_without_connector_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Subject: Pilot\n\nBody"
    document = Document(
        id=uuid4(),
        connector_id=uuid4(),
        external_id="email-1",
        file_path="/INBOX/thread/pilot.eml",
        file_name="pilot.eml",
        mime_type="message/rfc822",
        parse_status="indexed",
        sync_status="synced",
        allowed_user_ids=[],
        allowed_group_ids=[],
        metadata_json={"stored_payload_b64": base64.b64encode(payload).decode("ascii")},
    )
    auth = SimpleNamespace()

    async def fake_get_visible_to_auth(self, document_id: str, current_auth: object) -> Document:
        assert document_id == str(document.id)
        assert current_auth is auth
        return document

    monkeypatch.setattr(
        document_routes.DocumentRepository,
        "get_visible_to_auth",
        fake_get_visible_to_auth,
    )
    monkeypatch.setattr(
        document_routes.ConnectorRepository,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("connector lookup should not run")
        ),
    )

    response = await document_routes.get_document_original(
        str(document.id),
        session=SimpleNamespace(),
        identity=SimpleNamespace(auth=auth),
    )

    assert response.body == payload
    assert response.media_type == "message/rfc822"
