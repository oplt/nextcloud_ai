from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.auth import extract_access_token
from backend.core.exceptions import AuthenticationError, AuthorizationError
from backend.core.security import AuthContext, app_token_service
from backend.db.models import User
from backend.db.repo.user import UserRepository
from backend.db.session import get_db_session


DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@dataclass(slots=True)
class AuthenticatedUser:
    user: User
    auth: AuthContext


async def get_current_identity(request: Request, session: DbSessionDep) -> AuthenticatedUser:
    token = extract_access_token(request)
    if not token:
        raise AuthenticationError("Missing access token")
    try:
        auth = app_token_service.decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid access token") from exc

    user = await UserRepository(session).get(auth.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User is inactive or missing")
    return AuthenticatedUser(user=user, auth=auth)


CurrentIdentityDep = Annotated[AuthenticatedUser, Depends(get_current_identity)]


async def get_current_user(identity: CurrentIdentityDep) -> User:
    return identity.user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_current_superuser(identity: CurrentIdentityDep) -> AuthenticatedUser:
    if not identity.user.is_superuser:
        raise AuthorizationError()
    return identity


SuperUserDep = Annotated[AuthenticatedUser, Depends(get_current_superuser)]
