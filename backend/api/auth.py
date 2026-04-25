from __future__ import annotations

from fastapi import Request, Response

from ..core.config import settings
from ..core.csrf import clear_csrf_cookie, issue_csrf_cookie


def extract_access_token(request: Request) -> str | None:
    return request.cookies.get(settings.AUTH_COOKIE_NAME)


def set_session_cookies(response: Response, access_token: str) -> str:
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=access_token,
        max_age=settings.auth_cookie_max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path="/",
    )
    return issue_csrf_cookie(response)


def clear_session_cookies(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    clear_csrf_cookie(response)
