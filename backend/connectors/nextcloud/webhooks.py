from __future__ import annotations

import hmac
import json
from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from backend.api.deps import DbSessionDep
from backend.connectors.nextcloud.config import (
    NextcloudBridgeSettings,
    get_nextcloud_settings,
)
from backend.connectors.nextcloud.schemas import NextcloudWebhookEvent
from backend.services.nextcloud_automation_service import NextcloudAutomationService

router = APIRouter(prefix="/nextcloud", tags=["nextcloud-webhooks"])


def _verify_secret(raw_body: bytes, signature: str | None, secret: str | None) -> None:
    if not secret:
        return
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing webhook signature"
        )
    expected = hmac.new(secret.encode("utf-8"), raw_body, sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature"
        )


@router.post("/webhooks")
async def receive_nextcloud_webhook(
    request: Request,
    session: DbSessionDep,
    settings: Annotated[NextcloudBridgeSettings, Depends(get_nextcloud_settings)],
    x_webhook_signature: Annotated[
        str | None, Header(alias="X-Webhook-Signature")
    ] = None,
) -> dict[str, object]:
    raw_body = await request.body()
    secret = (
        settings.webhook_secret.get_secret_value() if settings.webhook_secret else None
    )
    _verify_secret(raw_body, x_webhook_signature, secret)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload must be JSON",
        ) from exc

    connector_payload = payload.get("connector")
    connector_id = payload.get("connector_id")
    if connector_id is None and isinstance(connector_payload, dict):
        connector_id = connector_payload.get("id")

    event = NextcloudWebhookEvent(
        event=str(
            payload.get("event")
            or payload.get("type")
            or payload.get("action")
            or "unknown"
        ),
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
    result = await NextcloudAutomationService(session).dispatch_webhook_event(event)
    return {**result.to_dict(), "event": event.model_dump(mode="json")}
