from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.connectors.nextcloud.schemas import Principal
from backend.core.security import AppTokenService, get_app_security_settings

bearer_scheme = HTTPBearer(auto_error=False)


def get_app_token_service() -> AppTokenService:
    return AppTokenService(get_app_security_settings())


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    token_service: Annotated[AppTokenService, Depends(get_app_token_service)],
) -> Principal:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return token_service.decode_access_token(credentials.credentials)
    except Exception as exc:  # pragma: no cover - security boundary
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token") from exc
