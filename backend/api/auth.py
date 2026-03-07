from __future__ import annotations

from fastapi import Request

from backend.core.config import settings



def extract_access_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization")
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return request.cookies.get(settings.AUTH_COOKIE_NAME)
