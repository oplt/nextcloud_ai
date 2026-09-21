from __future__ import annotations

from datetime import datetime, timezone

from .client import AsyncNextcloudClient
from .identity import (
    namespace_nc_group,
    namespace_nc_user,
    share_has_read,
    share_is_expired,
    share_is_password_protected,
)
from .schemas import AccessControlEntry, ShareGrant

USER_SHARE = 0
GROUP_SHARE = 1
PUBLIC_LINK_SHARE = 3
EMAIL_SHARE = 4
FEDERATED_SHARE = 6
CIRCLE_SHARE = 7
TALK_CONVERSATION_SHARE = 10

# Fail closed: these grant types are not mapped into corpus ACL principals.
UNSUPPORTED_SHARE_TYPES = frozenset(
    {FEDERATED_SHARE, CIRCLE_SHARE, TALK_CONVERSATION_SHARE, EMAIL_SHARE}
)


class NextcloudPermissionService:
    def __init__(self, client: AsyncNextcloudClient) -> None:
        self.client = client

    async def build_acl_for_path(
        self,
        remote_path: str,
        owner_user_id: str | None = None,
        *,
        instance_base_url: str | None = None,
        now: datetime | None = None,
    ) -> AccessControlEntry:
        shares = await self.client.get_shares(remote_path)
        base_url = instance_base_url or str(self.client.config.base_url)
        allowed_user_ids: set[str] = set()
        allowed_group_ids: set[str] = set()
        unresolved_share_types: set[int] = set()
        public_link_readable_open = False
        public_link_notes: list[str] = []
        current = now or datetime.now(timezone.utc)

        if owner_user_id:
            allowed_user_ids.add(namespace_nc_user(base_url, owner_user_id))

        for share in shares:
            if share.uid_owner:
                owner_user_id = owner_user_id or share.uid_owner
                allowed_user_ids.add(namespace_nc_user(base_url, share.uid_owner))

            applied = self._apply_share(
                share,
                allowed_user_ids,
                allowed_group_ids,
                unresolved_share_types,
                instance_base_url=base_url,
                now=current,
            )
            if share.share_type == PUBLIC_LINK_SHARE:
                if applied == "public_open_read":
                    public_link_readable_open = True
                    public_link_notes.append("open_read_link_present")
                elif applied == "public_ignored":
                    public_link_notes.append("public_link_not_usable_for_corpus")

        return AccessControlEntry(
            path=remote_path,
            owner_user_id=(
                namespace_nc_user(base_url, owner_user_id) if owner_user_id else None
            ),
            allowed_user_ids=sorted(allowed_user_ids),
            allowed_group_ids=sorted(allowed_group_ids),
            # Never grant global app-user visibility from a possession-based link.
            public_link_enabled=False,
            public_link_open_read_observed=public_link_readable_open,
            unresolved_share_types=sorted(unresolved_share_types),
            public_link_notes=public_link_notes,
            raw_shares=shares,
        )

    @staticmethod
    def _apply_share(
        share: ShareGrant,
        allowed_user_ids: set[str],
        allowed_group_ids: set[str],
        unresolved_share_types: set[int],
        *,
        instance_base_url: str,
        now: datetime,
    ) -> str:
        if share_is_expired(share.expiration, now=now):
            return "expired"
        if not share_has_read(share.permissions):
            return "no_read"

        if share.share_type == USER_SHARE and share.share_with:
            allowed_user_ids.add(namespace_nc_user(instance_base_url, share.share_with))
            return "user"

        if share.share_type == GROUP_SHARE and share.share_with:
            allowed_group_ids.add(
                namespace_nc_group(instance_base_url, share.share_with)
            )
            return "group"

        if share.share_type == PUBLIC_LINK_SHARE:
            # Password/protected links and open links are possession-based.
            # They must not become corpus-wide visibility for authenticated users.
            if share_is_password_protected(share.password):
                return "public_ignored"
            if share_has_read(share.permissions):
                return "public_open_read"
            return "public_ignored"

        if share.share_type in UNSUPPORTED_SHARE_TYPES:
            unresolved_share_types.add(int(share.share_type))
            return "unsupported"

        unresolved_share_types.add(int(share.share_type))
        return "unsupported"
