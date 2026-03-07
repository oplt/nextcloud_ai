from __future__ import annotations

import hmac
import json
from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from .config import NextcloudSettings, get_nextcloud_settings
from .schemas import NextcloudWebhookEvent

router = APIRouter(prefix="/api/v1/nextcloud", tags=["nextcloud-webhooks"])


def _verify_secret(raw_body: bytes, signature: str | None, secret: str | None) -> None:
    if not secret:
        return
    if not signature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing webhook signature")
    expected = hmac.new(secret.encode("utf-8"), raw_body, sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")


@router.post("/webhooks")
async def receive_nextcloud_webhook(
    request: Request,
    settings: Annotated[NextcloudSettings, Depends(get_nextcloud_settings)],
    x_webhook_signature: Annotated[str | None, Header(alias="X-Webhook-Signature")] = None,
) -> dict[str, object]:
    raw_body = await request.body()
    secret = settings.webhook_secret.get_secret_value() if settings.webhook_secret else None
    _verify_secret(raw_body, x_webhook_signature, secret)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook payload must be JSON") from exc

    event = NextcloudWebhookEvent(
        event=str(payload.get("event") or payload.get("type") or "unknown"),
        subject=payload.get("subject"),
        path=payload.get("path"),
        actor=payload.get("actor"),
        timestamp=payload.get("timestamp"),
        raw=payload,
    )
    # Enqueue your background sync job here.
    return {"accepted": True, "event": event.model_dump(mode="json")}
