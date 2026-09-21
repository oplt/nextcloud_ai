"""Deprecated compatibility re-export. Prefer ``connectors.nextcloud.webhooks``."""

from __future__ import annotations

import warnings

from .webhooks import router

warnings.warn(
    "Import webhook router from backend.connectors.nextcloud.webhooks; "
    "nextcloud_events is a compatibility shim and will be removed.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["router"]
