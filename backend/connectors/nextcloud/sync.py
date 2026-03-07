from __future__ import annotations

from collections.abc import AsyncIterator

from backend.connectors.nextcloud.client import AsyncNextcloudClient
from backend.connectors.nextcloud.permissions import NextcloudPermissionService
from backend.connectors.nextcloud.schemas import DavNode, SyncBatchItem


class NextcloudSyncService:
    def __init__(self, client: AsyncNextcloudClient, permissions: NextcloudPermissionService) -> None:
        self.client = client
        self.permissions = permissions

    async def crawl(self, root_path: str = "/") -> AsyncIterator[SyncBatchItem]:
        async for node in self._walk(root_path):
            if node.is_directory:
                continue
            acl = await self.permissions.build_acl_for_path(node.path)
            yield SyncBatchItem(node=node, acl=acl)

    async def snapshot(self, root_path: str = "/") -> list[SyncBatchItem]:
        items: list[SyncBatchItem] = []
        async for item in self.crawl(root_path):
            items.append(item)
        return items

    async def fetch_file_bytes(self, remote_path: str) -> bytes:
        return await self.client.download_file(remote_path)

    async def _walk(self, remote_path: str) -> AsyncIterator[DavNode]:
        listing = await self.client.list_directory(remote_path, depth=1)
        normalized_current = remote_path.rstrip("/") or "/"
        for node in listing:
            if node.path.rstrip("/") == normalized_current.rstrip("/"):
                continue
            yield node
            if node.is_directory:
                async for child in self._walk(node.path):
                    yield child
