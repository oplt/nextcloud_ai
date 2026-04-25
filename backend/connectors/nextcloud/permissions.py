from __future__ import annotations

from .client import AsyncNextcloudClient
from .schemas import AccessControlEntry, ShareGrant

USER_SHARE = 0
GROUP_SHARE = 1
PUBLIC_LINK_SHARE = 3
FEDERATED_SHARE = 6
CIRCLE_SHARE = 7
TALK_CONVERSATION_SHARE = 10


class NextcloudPermissionService:
    def __init__(self, client: AsyncNextcloudClient) -> None:
        self.client = client

    async def build_acl_for_path(
        self, remote_path: str, owner_user_id: str | None = None
    ) -> AccessControlEntry:
        shares = await self.client.get_shares(remote_path)
        allowed_user_ids: set[str] = set()
        allowed_group_ids: set[str] = set()
        public_link_enabled = False

        if owner_user_id:
            allowed_user_ids.add(owner_user_id)

        for share in shares:
            self._apply_share(share, allowed_user_ids, allowed_group_ids)
            if share.share_type == PUBLIC_LINK_SHARE:
                public_link_enabled = True
            if share.uid_owner:
                owner_user_id = owner_user_id or share.uid_owner

        return AccessControlEntry(
            path=remote_path,
            owner_user_id=owner_user_id,
            allowed_user_ids=sorted(allowed_user_ids),
            allowed_group_ids=sorted(allowed_group_ids),
            public_link_enabled=public_link_enabled,
            raw_shares=shares,
        )

    @staticmethod
    def _apply_share(
        share: ShareGrant, allowed_user_ids: set[str], allowed_group_ids: set[str]
    ) -> None:
        if share.share_type == USER_SHARE and share.share_with:
            allowed_user_ids.add(share.share_with)
            return
        if share.share_type == GROUP_SHARE and share.share_with:
            allowed_group_ids.add(share.share_with)
            return
        if (
            share.share_type in {FEDERATED_SHARE, CIRCLE_SHARE, TALK_CONVERSATION_SHARE}
            and share.share_with
        ):
            allowed_group_ids.add(share.share_with)
