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


def _webhook_replay_store(settings_obj: NextcloudBridgeSettings) -> ReplayStore | None:
    redis_url = settings_obj.bridge_redis_url or settings.nextcloud_event_redis_url
    if redis_url:
        return RedisReplayStore(redis_url=redis_url, namespace="nextcloud-webhook:event")
    if settings.APP_ENV in {"development", "test"}:
        return InMemoryReplayStore(namespace="nextcloud-webhook:event")
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
    expected = hmac.new(secret.encode("utf-8"), raw_body, sha256).hexdigest()
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
    ts = _parse_timestamp(header_timestamp)
    if ts is None:
        ts = _parse_timestamp(payload_timestamp)
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
    return f"{timestamp}:{digest}"


@router.post("/webhooks")
async def receive_nextcloud_webhook(
    request: Request,
    session: DbSessionDep,
    bridge_settings: Annotated[NextcloudBridgeSettings, Depends(get_nextcloud_settings)],
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

    # Never accept unsigned traffic. Missing secret disables the endpoint.
    require_secret = True
    secret = (
        bridge_settings.webhook_secret.get_secret_value()
        if bridge_settings.webhook_secret
        else None
    )
    _verify_secret(
        raw_body,
        x_webhook_signature,
        secret,
        require_secret=require_secret,
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

    event_name = (
        payload.get("event") or payload.get("type") or payload.get("action")
    )
    if not event_name or not str(event_name).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload missing event/type/action",
        )

    timestamp = _verify_freshness(
        header_timestamp=x_webhook_timestamp,
        payload_timestamp=payload.get("timestamp"),
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
