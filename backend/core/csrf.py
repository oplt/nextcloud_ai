from __future__ import annotations

import secrets

from fastapi import Request, Response

from ..core.config import settings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
CSRF_EXEMPT_PATHS = frozenset(
    {
        f"{settings.API_V1_PREFIX}/auth/logout",
        f"{settings.API_V1_PREFIX}/auth/nextcloud/exchange",
        f"{settings.API_V1_PREFIX}/auth/nextcloud/sso/consume",
        f"{settings.API_V1_PREFIX}/nextcloud/webhooks",
    }
)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def issue_csrf_cookie(response: Response, token: str | None = None) -> str:
    csrf_token = token or generate_csrf_token()
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=settings.auth_cookie_max_age,
        httponly=False,
        secure=settings.csrf_cookie_secure,
        samesite=settings.csrf_cookie_samesite,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path="/",
    )
    return csrf_token


def ensure_csrf_cookie(request: Request, response: Response) -> str:
    existing = request.cookies.get(settings.CSRF_COOKIE_NAME)
    if existing:
        response.set_cookie(
            key=settings.CSRF_COOKIE_NAME,
            value=existing,
            max_age=settings.auth_cookie_max_age,
            httponly=False,
            secure=settings.csrf_cookie_secure,
            samesite=settings.csrf_cookie_samesite,
            domain=settings.AUTH_COOKIE_DOMAIN,
            path="/",
        )
        return existing
    return issue_csrf_cookie(response)


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.CSRF_COOKIE_NAME,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path="/",
        secure=settings.csrf_cookie_secure,
        samesite=settings.csrf_cookie_samesite,
    )


def should_enforce_csrf(request: Request) -> bool:
    if request.method.upper() in SAFE_METHODS:
        return False
    path = request.url.path.rstrip("/") or "/"
    return path not in CSRF_EXEMPT_PATHS


def validate_csrf_request(request: Request) -> str | None:
    if not should_enforce_csrf(request):
        return None

    cookie_token = request.cookies.get(settings.CSRF_COOKIE_NAME)
    header_token = request.headers.get(settings.CSRF_HEADER_NAME)

    if not cookie_token or not header_token:
        return "Missing CSRF token"
    if not secrets.compare_digest(cookie_token, header_token):
        return "Invalid CSRF token"
    return None
