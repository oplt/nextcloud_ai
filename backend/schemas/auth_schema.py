from __future__ import annotations

from pydantic import BaseModel, EmailStr

from .user_schema import UserRead


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class IssuedAuthSession(BaseModel):
    access_token: str
    expires_in: int
    user: UserRead


class AuthSessionResponse(BaseModel):
    expires_in: int
    user: UserRead


class CsrfTokenResponse(BaseModel):
    csrf_token: str
