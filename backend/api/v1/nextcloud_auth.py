from __future__ import annotations

import json
from functools import lru_cache
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from ..auth import set_session_cookies
from ..deps import DbSessionDep
from ...connectors.nextcloud import BridgeTokenCodec, get_nextcloud_settings
from ...connectors.nextcloud.exceptions import BridgeTokenError
from ...connectors.nextcloud.replay_store import RedisReplayStore
from ...connectors.nextcloud.schemas import BridgeExchangeRequest, Principal
from ...core.config import settings
from ...schemas.auth_schema import AuthSessionResponse, IssuedAuthSession
from ...services.auth_service import AuthService

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
) -> IssuedAuthSession:
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
    set_session_cookies(response, auth_session.access_token)
    return AuthSessionResponse(
        expires_in=auth_session.expires_in,
        user=auth_session.user,
    )


@router.get("/sso/consume")
def sso_consume_get_redirect() -> RedirectResponse:
    """POST /sso/consume leaves this URL in history; refresh/new-tab GET used to 404."""
    return RedirectResponse(
        url=settings.frontend_redirect_url,
        status_code=status.HTTP_302_FOUND,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/sso/consume")
async def consume_nextcloud_bridge_token(
    bridge_token: Annotated[str, Form(...)],
    session: DbSessionDep,
    codec: Annotated[BridgeTokenCodec, Depends(get_bridge_codec)],
):
    """Return HTML that navigates to the SPA.

    Do not use an HTTP redirect (303) here: the POST is submitted from a
    Nextcloud page whose CSP `form-action` allows the API origin but not the
    SPA; Chrome blocks redirect targets that are not listed in that directive
    (see nextcloud/server#29317), leaving users stuck on the bridge page.
    """
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
    set_session_cookies(response, auth_session.access_token)
    return response
