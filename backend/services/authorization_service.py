from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from ..core.exceptions import AuthorizationError
from ..core.security import AuthContext, auth_user_identifiers

if TYPE_CHECKING:
    from ..db.models import Connector, SyncJob, User


ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_ADMIN: frozenset({"*"}),
    ROLE_OPERATOR: frozenset(
        {
            "audit:read_owned",
            "chat:use",
            "connectors:create",
            "connectors:read",
            "connectors:test",
            "connectors:update_owned",
            "connectors:delete_owned",
            "connectors:sync_owned",
            "documents:read",
            "documents:reindex",
            "jobs:read",
            "jobs:retry_owned",
        }
    ),
    ROLE_VIEWER: frozenset(
        {
            "chat:use",
            "connectors:read",
            "documents:read",
            "jobs:read",
        }
    ),
}


def normalize_role_name(auth: AuthContext, user: "User | None" = None) -> str:
    if auth.is_superuser or (user is not None and user.is_superuser):
        return ROLE_ADMIN
    role_name = (user.role.name if user is not None and user.role else auth.role_name) or ROLE_VIEWER
    return role_name.lower()


def has_permission(
    permission: str,
    *,
    auth: AuthContext,
    user: "User | None" = None,
) -> bool:
    role_name = normalize_role_name(auth, user)
    permissions = ROLE_PERMISSIONS.get(role_name, frozenset())
    return "*" in permissions or permission in permissions


def ensure_permission(
    permission: str,
    *,
    auth: AuthContext,
    user: "User | None" = None,
) -> None:
    if not has_permission(permission, auth=auth, user=user):
        raise AuthorizationError(f"Missing permission: {permission}")


def connector_is_visible_to_identity(
    connector: "Connector",
    *,
    auth: AuthContext,
    user: "User",
) -> bool:
    if has_permission("connectors:read", auth=auth, user=user) and normalize_role_name(auth, user) == ROLE_ADMIN:
        return True
    return connector.owner_user_id == user.id


def connector_is_manageable_by_identity(
    connector: "Connector",
    *,
    auth: AuthContext,
    user: "User",
) -> bool:
    if normalize_role_name(auth, user) == ROLE_ADMIN:
        return True
    return connector.owner_user_id == user.id


def job_is_visible_to_identity(
    job: "SyncJob",
    connector: "Connector | None",
    *,
    auth: AuthContext,
    user: "User",
) -> bool:
    if normalize_role_name(auth, user) == ROLE_ADMIN:
        return True
    if job.requested_by_id == user.id:
        return True
    if connector is None:
        return False
    return connector.owner_user_id == user.id


def parse_csv_query_values(raw_values: Iterable[str] | None) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for raw in raw_values or []:
        for candidate in raw.split(","):
            normalized = candidate.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            values.append(normalized)
    return values


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
    user_identifiers = set(auth_user_identifiers(auth))
    if user_identifiers.intersection(allowed_user_ids):
        return True
    if owner_external_id and owner_external_id in user_identifiers:
        return True
    if auth.groups and set(auth.groups).intersection(allowed_group_ids):
        return True
    return False
