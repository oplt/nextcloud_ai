from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from .client import AsyncNextcloudClient
from .permissions import NextcloudPermissionService
from .schemas import DavNode, SyncBatchItem


class NextcloudSyncService:
    def __init__(
        self,
        client: AsyncNextcloudClient,
        permissions: NextcloudPermissionService,
        *,
        acl_concurrency: int = 8,
    ) -> None:
        self.client = client
        self.permissions = permissions
        self.acl_concurrency = max(1, acl_concurrency)

    async def crawl(self, root_path: str = "/") -> AsyncIterator[SyncBatchItem]:
        for item in await self.snapshot(root_path):
            yield item

    async def snapshot(self, root_path: str = "/") -> list[SyncBatchItem]:
        nodes = [node async for node in self._walk(root_path) if not node.is_directory]
        if not nodes:
            return []

        semaphore = asyncio.Semaphore(self.acl_concurrency)

        async def build_item(node: DavNode) -> SyncBatchItem:
            async with semaphore:
                acl = await self.permissions.build_acl_for_path(
                    node.path, owner_user_id=self.client.config.username
                )
            return SyncBatchItem(node=node, acl=acl)

        return list(await asyncio.gather(*(build_item(node) for node in nodes)))

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
