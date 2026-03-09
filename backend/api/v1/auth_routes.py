from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from backend.api.auth import clear_session_cookies, set_session_cookies
from backend.api.deps import CurrentIdentityDep, DbSessionDep
from backend.core.csrf import ensure_csrf_cookie
from backend.schemas.auth_schema import (
    AuthSessionResponse,
    CsrfTokenResponse,
    LoginRequest,
)
from backend.schemas.user_schema import UserRead
from backend.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/csrf", response_model=CsrfTokenResponse)
async def issue_csrf_token(request: Request, response: Response) -> CsrfTokenResponse:
    csrf_token = ensure_csrf_cookie(request, response)
    response.headers["Cache-Control"] = "no-store"
    return CsrfTokenResponse(csrf_token=csrf_token)


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
    set_session_cookies(response, auth_session.access_token)
    return AuthSessionResponse(
        expires_in=auth_session.expires_in,
        user=auth_session.user,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(response)
    return response


@router.get("/me", response_model=UserRead)
async def read_me(
    request: Request, response: Response, identity: CurrentIdentityDep
) -> UserRead:
    ensure_csrf_cookie(request, response)
    return UserRead.model_validate(identity.user)
