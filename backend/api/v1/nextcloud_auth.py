from __future__ import annotations

import json
from functools import lru_cache
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Response, status
from fastapi.responses import HTMLResponse

from backend.connectors.nextcloud import BridgeTokenCodec, get_nextcloud_settings
from backend.connectors.nextcloud.exceptions import BridgeTokenError
from backend.connectors.nextcloud.replay_store import RedisReplayStore
from backend.connectors.nextcloud.schemas import BridgeExchangeRequest, Principal
from backend.core.config import settings
from backend.schemas.auth_schema import AuthSessionResponse
from backend.services.auth_service import AuthService
from backend.api.deps import DbSessionDep

router = APIRouter(prefix="/auth/nextcloud", tags=["nextcloud-auth"])


@lru_cache(maxsize=1)
def get_bridge_codec() -> BridgeTokenCodec:
    bridge_settings = get_nextcloud_settings()
    replay_store = (
        RedisReplayStore(redis_url=bridge_settings.bridge_redis_url)
        if bridge_settings.bridge_redis_url
        else None
    )
    return BridgeTokenCodec(settings=bridge_settings, replay_store=replay_store)


async def _exchange_principal(
    session: DbSessionDep, principal: Principal
) -> AuthSessionResponse:
    return await AuthService(session).sync_nextcloud_principal(principal)


@router.post("/exchange", response_model=AuthSessionResponse)
async def exchange_nextcloud_bridge_token(
    payload: BridgeExchangeRequest,
    response: Response,
    session: DbSessionDep,
    codec: Annotated[BridgeTokenCodec, Depends(get_bridge_codec)],
) -> AuthSessionResponse:
    try:
        claims = await codec.verify_and_consume(payload.bridge_token)
    except BridgeTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    auth_session = await _exchange_principal(
        session,
        Principal(
            sub=claims.sub,
            username=claims.preferred_username,
            display_name=claims.display_name,
            email=claims.email,
            groups=claims.groups,
            nc_base_url=claims.nc_base_url,
        ),
    )
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=auth_session.access_token,
        max_age=settings.auth_cookie_max_age,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path="/",
    )
    return auth_session


@router.post("/sso/consume")
async def consume_nextcloud_bridge_token(
    bridge_token: Annotated[str, Form(...)],
    session: DbSessionDep,
    codec: Annotated[BridgeTokenCodec, Depends(get_bridge_codec)],
):
    try:
        claims = await codec.verify_and_consume(bridge_token)
    except BridgeTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    auth_session = await _exchange_principal(
        session,
        Principal(
            sub=claims.sub,
            username=claims.preferred_username,
            display_name=claims.display_name,
            email=claims.email,
            groups=claims.groups,
            nc_base_url=claims.nc_base_url,
        ),
    )
    frontend_url = settings.frontend_redirect_url
    escaped_frontend_url = escape(frontend_url, quote=True)
    frontend_url_js = json.dumps(frontend_url)
    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="0;url={escaped_frontend_url}">
    <title>Signing in…</title>
  </head>
  <body>
    <p>Sign-in complete. Redirecting…</p>
    <script>
      window.location.replace({frontend_url_js});
    </script>
    <noscript>
      <p><a href="{escaped_frontend_url}">Continue to the workspace</a></p>
    </noscript>
  </body>
</html>"""
    response = HTMLResponse(content=html, status_code=status.HTTP_200_OK)
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=auth_session.access_token,
        max_age=settings.auth_cookie_max_age,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path="/",
    )
    return response
