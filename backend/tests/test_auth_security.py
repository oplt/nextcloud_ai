from __future__ import annotations

from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

from backend.api.auth import extract_access_token, set_session_cookies
from backend.core.config import settings
from backend.core.csrf import should_enforce_csrf, validate_csrf_request
from backend.main import app


def make_request(
    method: str,
    path: str,
    *,
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> Request:
    scope_headers: list[tuple[bytes, bytes]] = []
    if cookies:
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        scope_headers.append((b"cookie", cookie_header.encode("utf-8")))
    for key, value in (headers or {}).items():
        scope_headers.append((key.lower().encode("utf-8"), value.encode("utf-8")))

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": scope_headers,
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "http_version": "1.1",
        }
    )


def test_extract_access_token_reads_cookie_only() -> None:
    request = make_request(
        "GET",
        "/api/v1/auth/me",
        cookies={settings.AUTH_COOKIE_NAME: "cookie-token"},
        headers={"Authorization": "Bearer header-token"},
    )

    assert extract_access_token(request) == "cookie-token"


def test_extract_access_token_ignores_bearer_header_without_cookie() -> None:
    request = make_request(
        "GET",
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer header-token"},
    )

    assert extract_access_token(request) is None


def test_csrf_validation_requires_matching_cookie_and_header() -> None:
    request = make_request(
        "POST",
        "/api/v1/connectors",
        cookies={settings.CSRF_COOKIE_NAME: "csrf-cookie"},
    )

    assert validate_csrf_request(request) == "Missing CSRF token"


def test_csrf_validation_accepts_matching_cookie_and_header() -> None:
    request = make_request(
        "POST",
        "/api/v1/connectors",
        cookies={settings.CSRF_COOKIE_NAME: "csrf-cookie"},
        headers={settings.CSRF_HEADER_NAME: "csrf-cookie"},
    )

    assert validate_csrf_request(request) is None


def test_csrf_validation_exempts_nextcloud_webhooks() -> None:
    request = make_request("POST", "/api/v1/nextcloud/webhooks")

    assert should_enforce_csrf(request) is False
    assert validate_csrf_request(request) is None


def test_csrf_validation_exempts_logout() -> None:
    request = make_request("POST", "/api/v1/auth/logout")

    assert should_enforce_csrf(request) is False
    assert validate_csrf_request(request) is None


def test_set_session_cookies_sets_auth_and_csrf_cookies() -> None:
    response = Response()

    set_session_cookies(response, "session-token")

    set_cookie_headers = [
        value.decode("utf-8")
        for key, value in response.raw_headers
        if key == b"set-cookie"
    ]
    assert any(settings.AUTH_COOKIE_NAME in header for header in set_cookie_headers)
    assert any(settings.CSRF_COOKIE_NAME in header for header in set_cookie_headers)


def test_logout_returns_explicit_204_response() -> None:
    client = TestClient(app)

    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    set_cookie_headers = response.headers.get("set-cookie", "")
    assert settings.AUTH_COOKIE_NAME in set_cookie_headers
    assert settings.CSRF_COOKIE_NAME in set_cookie_headers
