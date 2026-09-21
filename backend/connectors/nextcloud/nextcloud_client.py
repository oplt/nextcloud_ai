"""Deprecated compatibility re-export. Prefer ``connectors.nextcloud.client``."""

from __future__ import annotations

import warnings

from .client import AsyncNextcloudClient

warnings.warn(
    "Import AsyncNextcloudClient from backend.connectors.nextcloud.client; "
    "nextcloud_client is a compatibility shim and will be removed.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["AsyncNextcloudClient"]
