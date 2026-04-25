from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import extract_access_token
from ..core.exceptions import AuthenticationError, AuthorizationError
from ..core.security import AuthContext, app_token_service
from ..db.models import User
from ..db.repo.user import UserRepository
from ..db.session import get_db_session
from ..services.authorization_service import ensure_permission


DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@dataclass(slots=True)
class AuthenticatedUser:
    user: User
    auth: AuthContext


async def get_current_identity(
    request: Request, session: DbSessionDep
) -> AuthenticatedUser:
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
    auth.is_superuser = user.is_superuser
    auth.role_name = user.role.name if user.role else auth.role_name
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


def permission_required(permission: str):
    async def dependency(identity: CurrentIdentityDep) -> AuthenticatedUser:
        ensure_permission(permission, auth=identity.auth, user=identity.user)
        return identity

    return dependency
