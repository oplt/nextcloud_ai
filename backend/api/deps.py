from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.exceptions import AuthenticationError, AuthorizationError
from backend.core.security import decode_token
from backend.db.session import get_db_session
from backend.db.models import User
from backend.db.repo.user import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
TokenDep = Annotated[str, Depends(oauth2_scheme)]


async def get_current_user(
    session: DbSessionDep,
    token: TokenDep,
) -> User:
    try:
        payload = decode_token(token)
        subject = payload.get("sub")
        token_type = payload.get("type")
        if not subject or token_type != "access":
            raise AuthenticationError()
        user_id = UUID(subject)
    except (JWTError, ValueError):
        raise AuthenticationError()

    repo = UserRepository(session)
    user = await repo.get(user_id)
    if not user or not user.is_active:
        raise AuthenticationError()

    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_current_active_superuser(
    current_user: CurrentUserDep,
) -> User:
    if not current_user.is_superuser:
        raise AuthorizationError()
    return current_user


SuperUserDep = Annotated[User, Depends(get_current_active_superuser)]