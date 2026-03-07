from __future__ import annotations

from backend.core.security import AuthContext



def document_is_visible_to_auth(
    auth: AuthContext,
    *,
    owner_external_id: str | None,
    allowed_user_ids: list[str],
    allowed_group_ids: list[str],
    public_link_enabled: bool,
    is_deleted: bool,
) -> bool:
    if is_deleted:
        return False
    if auth.is_superuser:
        return True
    if public_link_enabled:
        return True
    if auth.external_subject and (auth.external_subject == owner_external_id or auth.external_subject in allowed_user_ids):
        return True
    if auth.groups and set(auth.groups).intersection(allowed_group_ids):
        return True
    return False
