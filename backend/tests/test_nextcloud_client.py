from __future__ import annotations

import pytest
import httpx
from pydantic import SecretStr

from backend.connectors.nextcloud.client import AsyncNextcloudClient
from backend.connectors.nextcloud.exceptions import NextcloudAPIError
from backend.connectors.nextcloud.config import NextcloudConnectorConfig


@pytest.mark.asyncio
async def test_href_to_path_decodes_url_encoded_names() -> None:
    client = AsyncNextcloudClient(
        NextcloudConnectorConfig(
            base_url="http://localhost",
            username="admin",
            app_password=SecretStr("app-password"),
        )
    )

    try:
        path = client._href_to_path(
            "/remote.php/dav/files/admin/Documents/Welcome%20to%20Nextcloud%20Hub.docx"
        )
    finally:
        await client.aclose()

    assert path == "/Documents/Welcome to Nextcloud Hub.docx"


@pytest.mark.asyncio
async def test_request_error_includes_upstream_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AsyncNextcloudClient(
        NextcloudConnectorConfig(
            base_url="https://localhost",
            username="admin",
            app_password=SecretStr("app-password"),
        )
    )

    async def fake_request(*args, **kwargs):
        request = httpx.Request("GET", "https://localhost/ocs/v2.php/cloud/user?format=json")
        raise httpx.ConnectError("All connection attempts failed", request=request)

    monkeypatch.setattr(client._client, "request", fake_request)

    with pytest.raises(NextcloudAPIError) as exc_info:
        await client.verify_credentials()

    await client.aclose()

    assert "Could not reach Nextcloud at https://localhost" in str(exc_info.value)
    assert "upstream_error=All connection attempts failed" in str(exc_info.value)
