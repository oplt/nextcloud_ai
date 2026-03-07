from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import JSONResponse, RedirectResponse

from backend.api.auth import get_current_principal
from backend.connectors.nextcloud import BridgeTokenCodec, get_nextcloud_settings
from backend.connectors.nextcloud.exceptions import BridgeTokenError
from backend.connectors.nextcloud.replay_store import RedisReplayStore
from backend.connectors.nextcloud.schemas import (
    BridgeExchangeRequest,
    BridgeExchangeResponse,
    Principal,
)
from backend.core.security import AppTokenService, get_app_security_settings

router = APIRouter(prefix="/api/v1/auth/nextcloud", tags=["nextcloud-auth"])


@lru_cache(maxsize=1)
def get_bridge_codec() -> BridgeTokenCodec:
    settings = get_nextcloud_settings()
    replay_store = (
        RedisReplayStore(redis_url=settings.bridge_redis_url)
        if settings.bridge_redis_url
        else None
    )
    return BridgeTokenCodec(settings=settings, replay_store=replay_store)


@lru_cache(maxsize=1)
def get_token_service() -> AppTokenService:
    return AppTokenService(get_app_security_settings())


@router.post("/exchange", response_model=BridgeExchangeResponse)
async def exchange_nextcloud_bridge_token(
    payload: BridgeExchangeRequest,
    codec: Annotated[BridgeTokenCodec, Depends(get_bridge_codec)],
    token_service: Annotated[AppTokenService, Depends(get_token_service)],
) -> BridgeExchangeResponse:
    try:
        claims = await codec.verify_and_consume(payload.bridge_token)
    except BridgeTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    principal = Principal(
        sub=claims.sub,
        username=claims.preferred_username,
        display_name=claims.display_name,
        email=claims.email,
        groups=claims.groups,
        nc_base_url=claims.nc_base_url,
    )
    access_token, expires_in = token_service.issue_access_token(principal)
    return BridgeExchangeResponse(access_token=access_token, expires_in=expires_in, principal=principal)


@router.post("/sso/consume")
async def consume_nextcloud_bridge_token(
    bridge_token: Annotated[str, Form(...)],
    codec: Annotated[BridgeTokenCodec, Depends(get_bridge_codec)],
    token_service: Annotated[AppTokenService, Depends(get_token_service)],
):
    try:
        claims = await codec.verify_and_consume(bridge_token)
    except BridgeTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    principal = Principal(
        sub=claims.sub,
        username=claims.preferred_username,
        display_name=claims.display_name,
        email=claims.email,
        groups=claims.groups,
        nc_base_url=claims.nc_base_url,
    )
    access_token, _ = token_service.issue_access_token(principal)

    settings = get_app_security_settings()
    redirect = RedirectResponse(url=settings.frontend_redirect_url, status_code=status.HTTP_303_SEE_OTHER)
    redirect.set_cookie(
        key=settings.cookie_name,
        value=access_token,
        max_age=settings.access_token_ttl_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )
    return redirect


@router.get("/me")
async def current_nextcloud_principal(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> JSONResponse:
    return JSONResponse(content=principal.model_dump(mode="json"))
