"""Deprecated compatibility re-export. Prefer ``connectors.nextcloud.sync``."""

from __future__ import annotations

import warnings

from .sync import NextcloudSyncService

warnings.warn(
    "Import NextcloudSyncService from backend.connectors.nextcloud.sync; "
    "nextcloud_sync is a compatibility shim and will be removed.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["NextcloudSyncService"]
