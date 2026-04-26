from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext
from pydantic import BaseModel, Field
import hashlib
import bcrypt  # Add direct bcrypt import

from .config import settings

# Use a more compatible CryptContext configuration
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12  # Explicitly set rounds for stability
)


class AuthContext(BaseModel):
    user_id: str
    auth_provider: Literal["local", "nextcloud"]
    external_subject: str | None = None
    username: str | None = None
    display_name: str | None = None
    email: str | None = None
    groups: list[str] = Field(default_factory=list)
    nextcloud_base_url: str | None = None
    is_superuser: bool = False
    role_name: str | None = None


def auth_user_identifiers(auth: AuthContext) -> list[str]:
    identifiers: list[str] = []
    seen: set[str] = set()
    for value in (auth.user_id, auth.external_subject, auth.username, auth.email):
        if not value:
            continue
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        identifiers.append(normalized)
    return identifiers


class ConnectorSecretCipher:
    def __init__(self, secret_key: bytes) -> None:
        self._fernet = Fernet(secret_key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Connector secret could not be decrypted") from exc


class AppTokenService:
    def issue_access_token(self, context: AuthContext) -> tuple[str, int]:
        now = datetime.now(tz=timezone.utc)
        expires_at = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        payload: dict[str, Any] = {
            "iss": settings.AUTH_ISSUER,
            "aud": settings.AUTH_AUDIENCE,
            "sub": context.user_id,
            "type": "access",
            "auth_provider": context.auth_provider,
            "external_subject": context.external_subject,
            "username": context.username,
            "display_name": context.display_name,
            "email": context.email,
            "groups": context.groups,
            "nextcloud_base_url": context.nextcloud_base_url,
            "is_superuser": context.is_superuser,
            "role_name": context.role_name,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        token = jwt.encode(
            payload,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithm="HS256",
        )
        return token, int((expires_at - now).total_seconds())

    def decode_access_token(self, token: str) -> AuthContext:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=["HS256"],
            audience=settings.AUTH_AUDIENCE,
            issuer=settings.AUTH_ISSUER,
            options={"require": ["iss", "aud", "sub", "exp", "iat", "nbf", "type"]},
        )
        if payload.get("type") != "access":
            raise jwt.InvalidTokenError("Unexpected token type")
        return AuthContext(
            user_id=payload["sub"],
            auth_provider=payload.get("auth_provider", "local"),
            external_subject=payload.get("external_subject"),
            username=payload.get("username"),
            display_name=payload.get("display_name"),
            email=payload.get("email"),
            groups=list(payload.get("groups", [])),
            nextcloud_base_url=payload.get("nextcloud_base_url"),
            is_superuser=bool(payload.get("is_superuser", False)),
            role_name=payload.get("role_name"),
        )


app_token_service = AppTokenService()
connector_secret_cipher = ConnectorSecretCipher(settings.vault_fernet_key)


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt with pre-hashing to handle long passwords.
    The SHA-256 pre-hash ensures we don't hit bcrypt's 72-byte limit.
    """
    # Pre-hash with SHA-256 to handle any password length
    pre_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()

    # Use bcrypt directly for better control
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(pre_hash.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.
    """
    pre_hash = hashlib.sha256(plain_password.encode('utf-8')).hexdigest()

    try:
        # Try bcrypt verification first
        return bcrypt.checkpw(
            pre_hash.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except ValueError:
        # Fall back to passlib if bcrypt direct fails
        return pwd_context.verify(pre_hash, hashed_password)


def is_password_strong(password: str) -> bool:
    if len(password) < 10:
        return False
    return (
            any(char.isupper() for char in password)
            and any(char.islower() for char in password)
            and any(char.isdigit() for char in password)
    )
