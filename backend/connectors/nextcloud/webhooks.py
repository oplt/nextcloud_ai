"""Nextcloud webhook ingress with required signatures outside development."""

from __future__ import annotations

import hmac
import json
import time
from hashlib import sha256
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError

from ...api.deps import DbSessionDep
from ...core.config import settings
from .config import (
    NextcloudBridgeSettings,
    get_nextcloud_settings,
)
from .replay_store import InMemoryReplayStore, RedisReplayStore, ReplayStore
from .schemas import NextcloudWebhookEvent
from ...services.nextcloud_automation_service import NextcloudAutomationService

router = APIRouter(prefix="/nextcloud", tags=["nextcloud-webhooks"])

_MAX_WEBHOOK_BODY_BYTES = 256_000
_DEFAULT_MAX_AGE_SECONDS = 300
_replay_stores: dict[str, ReplayStore] = {}


def _webhook_replay_store(settings_obj: NextcloudBridgeSettings) -> ReplayStore | None:
    redis_url = settings_obj.bridge_redis_url or settings.nextcloud_event_redis_url
    if redis_url:
        key = f"redis:{redis_url}"
        if key not in _replay_stores:
            _replay_stores[key] = RedisReplayStore(
                redis_url=redis_url,
                namespace="nextcloud-webhook:event",
            )
        return _replay_stores[key]
    if settings.APP_ENV in {"development", "test"}:
        key = f"memory:{settings.APP_ENV}"
        if key not in _replay_stores:
            _replay_stores[key] = InMemoryReplayStore(
                namespace="nextcloud-webhook:event"
            )
        return _replay_stores[key]
    return None


def _extract_signature(header_value: str | None) -> str | None:
    if not header_value:
        return None
    value = header_value.strip()
    if value.lower().startswith("sha256="):
        return value.split("=", 1)[1].strip()
    return value


def _verify_secret(
    raw_body: bytes,
    signature: str | None,
    secret: str | None,
    *,
    require_secret: bool,
    signed_timestamp: str | None = None,
) -> None:
    if not secret:
        if require_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Webhook endpoint disabled: NEXTCLOUD_WEBHOOK_SECRET is not configured",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook endpoint disabled without a configured secret",
        )
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing webhook signature",
        )
    provided = _extract_signature(signature)
    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing webhook signature",
        )
    signed_payload = raw_body
    if signed_timestamp is not None:
        signed_payload = signed_timestamp.strip().encode("utf-8") + b"." + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed_payload, sha256).hexdigest()
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )


def _parse_timestamp(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = int(value)
        # Accept ms timestamps.
        if ts > 10_000_000_000:
            ts //= 1000
        return ts
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.isdigit():
            ts = int(text)
            if ts > 10_000_000_000:
                ts //= 1000
            return ts
        from datetime import datetime

        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return int(parsed.timestamp())
    except ValueError:
        return None


def _verify_freshness(
    *,
    header_timestamp: str | None,
    payload_timestamp: object,
    max_age_seconds: int = _DEFAULT_MAX_AGE_SECONDS,
) -> int:
    header_ts = _parse_timestamp(header_timestamp)
    payload_ts = _parse_timestamp(payload_timestamp)
    if header_timestamp is not None and header_ts is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-Webhook-Timestamp",
        )
    if payload_timestamp is not None and payload_ts is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payload timestamp",
        )
    if header_ts is not None and payload_ts is not None and header_ts != payload_ts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook header and payload timestamps do not match",
        )
    # Prefer the body timestamp because it is covered by the body HMAC.
    ts = payload_ts if payload_ts is not None else header_ts
    if ts is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook timestamp missing (X-Webhook-Timestamp or payload.timestamp)",
        )
    now = int(time.time())
    if abs(now - ts) > max_age_seconds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook timestamp is stale or from the future",
        )
    return ts


def _event_id(payload: dict[str, Any], timestamp: int) -> str:
    for key in ("event_id", "id", "delivery_id", "uuid"):
        value = payload.get(key)
        if value:
            return str(value)
    digest = sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:32]
    # Keep body-identical deliveries stable even if an unsigned transport
    # timestamp changes. This prevents timestamp rotation from bypassing replay.
    return digest


@router.post("/webhooks")
async def receive_nextcloud_webhook(
    request: Request,
    session: DbSessionDep,
    bridge_settings: Annotated[
        NextcloudBridgeSettings, Depends(get_nextcloud_settings)
    ],
    x_webhook_signature: Annotated[
        str | None, Header(alias="X-Webhook-Signature")
    ] = None,
    x_webhook_timestamp: Annotated[
        str | None, Header(alias="X-Webhook-Timestamp")
    ] = None,
) -> dict[str, object]:
    raw_body = await request.body()
    if len(raw_body) > _MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Webhook payload too large",
        )

    secret = (
        bridge_settings.webhook_secret.get_secret_value()
        if bridge_settings.webhook_secret
        else None
    )
    if not secret:
        _verify_secret(
            raw_body,
            x_webhook_signature,
            secret,
            require_secret=True,
        )

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload must be JSON",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload must be a JSON object",
        )

    # Never accept unsigned traffic. A timestamp supplied only in the header
    # is covered by the signature as ``<timestamp>.<raw_body>``. When the body
    # carries its own timestamp, the legacy/raw-body HMAC remains valid because
    # freshness is then cryptographically bound inside the body.
    payload_timestamp = payload.get("timestamp")
    _verify_secret(
        raw_body,
        x_webhook_signature,
        secret,
        require_secret=True,
        signed_timestamp=(x_webhook_timestamp if payload_timestamp is None else None),
    )

    event_name = payload.get("event") or payload.get("type") or payload.get("action")
    if not event_name or not str(event_name).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload missing event/type/action",
        )

    timestamp = _verify_freshness(
        header_timestamp=x_webhook_timestamp,
        payload_timestamp=payload_timestamp,
    )

    replay_store = _webhook_replay_store(bridge_settings)
    if replay_store is not None:
        event_id = _event_id(payload, timestamp)
        accepted = await replay_store.mark_consumed(
            event_id, ttl_seconds=_DEFAULT_MAX_AGE_SECONDS * 2
        )
        if not accepted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Replay detected for webhook event",
            )

    connector_payload = payload.get("connector")
    connector_id = payload.get("connector_id")
    if connector_id is None and isinstance(connector_payload, dict):
        connector_id = connector_payload.get("id")

    try:
        event = NextcloudWebhookEvent(
            event=str(event_name),
            connector_id=connector_id,
            subject=payload.get("subject"),
            path=payload.get("path") or payload.get("file_path"),
            actor=payload.get("actor"),
            base_url=payload.get("base_url") or payload.get("nc_base_url"),
            username=payload.get("username") or payload.get("connector_username"),
            file_id=payload.get("file_id") or payload.get("id"),
            is_directory=payload.get("is_directory"),
            timestamp=payload.get("timestamp"),
            raw=payload,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook payload shape",
        ) from exc

    result = await NextcloudAutomationService(session).dispatch_webhook_event(event)
    return {**result.to_dict(), "event": event.model_dump(mode="json")}
