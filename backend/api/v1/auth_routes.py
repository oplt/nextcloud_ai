from __future__ import annotations

from fastapi import APIRouter, Response, status

from backend.api.deps import CurrentIdentityDep, DbSessionDep
from backend.core.config import settings
from backend.schemas.auth_schema import AuthSessionResponse, LoginRequest
from backend.schemas.user_schema import UserRead
from backend.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login", response_model=AuthSessionResponse, status_code=status.HTTP_200_OK
)
async def login(
    payload: LoginRequest, response: Response, session: DbSessionDep
) -> AuthSessionResponse:
    auth_service = AuthService(session)
    auth_session = await auth_service.login_with_password(
        payload.email, payload.password
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


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> Response:
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME, domain=settings.AUTH_COOKIE_DOMAIN, path="/"
    )
    return response


@router.get("/me", response_model=UserRead)
async def read_me(identity: CurrentIdentityDep) -> UserRead:
    return UserRead.model_validate(identity.user)
