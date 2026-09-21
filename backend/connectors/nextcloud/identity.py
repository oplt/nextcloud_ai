"""Nextcloud ACL identity helpers (namespaced principals, share permission bits)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from urllib.parse import urlparse

# Nextcloud OCS share permission bits:
# https://docs.nextcloud.com/server/latest/developer_manual/client_apis/OCS/ocs-share-api.html
NC_PERM_READ = 1
NC_PERM_UPDATE = 2
NC_PERM_CREATE = 4
NC_PERM_DELETE = 8
NC_PERM_SHARE = 16


def normalize_instance_key(base_url: str | None) -> str:
    """Stable instance key for namespacing principals (host[+path], lowercased)."""
    if not base_url:
        return "unknown"
    raw = str(base_url).strip()
    if not raw:
        return "unknown"
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or "").lower().rstrip(".")
    path = (parsed.path or "").rstrip("/")
    if not host and path:
        # urlparse("example.com/nextcloud") puts it in path
        host = path.lstrip("/").lower()
        path = ""
    key = f"{host}{path}" if path and path != "/" else host
    return key or "unknown"


def namespace_nc_user(base_url: str | None, user_id: str) -> str:
    return f"nc:{normalize_instance_key(base_url)}:user:{user_id.strip()}"


def namespace_nc_group(base_url: str | None, group_id: str) -> str:
    return f"nc:{normalize_instance_key(base_url)}:group:{group_id.strip()}"


def namespace_local_user(username: str) -> str:
    return f"local:user:{username.strip()}"


def namespace_local_email(email: str) -> str:
    return f"local:email:{email.strip().lower()}"


def share_has_read(permissions: int) -> bool:
    return bool(int(permissions) & NC_PERM_READ)


def parse_share_expiration(value: object) -> datetime | None:
    if value is None or value is False or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value).strip()
    if not text or text.lower() in {"false", "0", "none", "null"}:
        return None
    # OCS commonly returns YYYY-MM-DD
    try:
        if "T" in text or " " in text:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        day = date.fromisoformat(text[:10])
        # Expire at end of that UTC day.
        return datetime(
            day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc
        )
    except ValueError:
        return None


def share_is_expired(expiration: object, *, now: datetime | None = None) -> bool:
    parsed = parse_share_expiration(expiration)
    if parsed is None:
        return False
    current = now or datetime.now(timezone.utc)
    return current > parsed


def share_is_password_protected(password: object) -> bool:
    if password is True:
        return True
    if isinstance(password, str) and password.strip() and password.strip().lower() not in {
        "false",
        "0",
        "no",
        "none",
        "null",
    }:
        # OCS may return "yes" / non-empty marker without the secret itself.
        return True
    return False
