from __future__ import annotations

import pytest
from pydantic import SecretStr

from backend.connectors.nextcloud.client import AsyncNextcloudClient
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
