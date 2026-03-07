from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from backend.core.config import settings
from functools import lru_cache
import jwt
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.connectors.nextcloud.schemas import Principal


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (
            expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])


def is_password_strong(password: str) -> bool:
    if len(password) < 10:
        return False
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    return has_upper and has_lower and has_digit


class AppSecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_AUTH_",
        case_sensitive=False,
        extra="ignore",
    )

    jwt_secret: SecretStr = Field(..., description="FastAPI application JWT signing secret")
    issuer: str = Field(default="fastapi-app")
    audience: str = Field(default="fastapi-users")
    access_token_ttl_minutes: int = Field(default=15, ge=5, le=1440)
    cookie_name: str = Field(default="nc_ai_access_token")
    cookie_secure: bool = True
    cookie_samesite: str = Field(default="lax")
    cookie_domain: str | None = None
    frontend_redirect_url: str = Field(default="/app")


@lru_cache(maxsize=1)
def get_app_security_settings() -> AppSecuritySettings:
    return AppSecuritySettings()


class AppTokenService:
    def __init__(self, settings: AppSecuritySettings) -> None:
        self.settings = settings

    def issue_access_token(self, principal: Principal) -> tuple[str, int]:
        now = datetime.now(tz=timezone.utc)
        expires_at = now + timedelta(minutes=self.settings.access_token_ttl_minutes)
        payload: dict[str, Any] = {
            "iss": self.settings.issuer,
            "aud": self.settings.audience,
            "sub": principal.sub,
            "provider": principal.provider,
            "username": principal.username,
            "display_name": principal.display_name,
            "email": principal.email,
            "groups": principal.groups,
            "nc_base_url": principal.nc_base_url,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        token = jwt.encode(
            payload,
            self.settings.jwt_secret.get_secret_value(),
            algorithm="HS256",
        )
        return token, int((expires_at - now).total_seconds())

    def decode_access_token(self, token: str) -> Principal:
        decoded = jwt.decode(
            token,
            self.settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience=self.settings.audience,
            issuer=self.settings.issuer,
            options={"require": ["iss", "aud", "sub", "exp", "iat", "nbf"]},
        )
        return Principal(
            sub=decoded["sub"],
            provider="nextcloud",
            username=decoded["username"],
            display_name=decoded.get("display_name"),
            email=decoded.get("email"),
            groups=list(decoded.get("groups", [])),
            nc_base_url=decoded["nc_base_url"],
        )