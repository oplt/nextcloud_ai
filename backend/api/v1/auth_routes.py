from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import CurrentUserDep, DbSessionDep
from backend.core.exceptions import AuthenticationError
from backend.core.security import create_access_token, verify_password
from backend.db.repo.user import UserRepository
from backend.schemas.auth_schema import LoginRequest, LoginResponse, Token
from backend.schemas.user_schema import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
async def login(
        payload: LoginRequest,
        session: DbSessionDep,
) -> LoginResponse:
    repo = UserRepository(session)
    user = await repo.get_by_email(payload.email)

    if not user or not verify_password(payload.password, user.hashed_password):
        raise AuthenticationError(detail="Incorrect email or password")

    if not user.is_active:
        raise AuthenticationError(detail="Inactive user")

    token = create_access_token(str(user.id))
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=UserRead.model_validate(user),
    )


@router.get("/me", response_model=UserRead)
async def read_me(current_user: CurrentUserDep) -> UserRead:
    return UserRead.model_validate(current_user)