"""Deprecated compatibility re-export. Prefer ``connectors.nextcloud.permissions``."""

from __future__ import annotations

import warnings

from .permissions import NextcloudPermissionService

warnings.warn(
    "Import NextcloudPermissionService from backend.connectors.nextcloud.permissions; "
    "nextcloud_permissions is a compatibility shim and will be removed.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["NextcloudPermissionService"]
