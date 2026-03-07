from __future__ import annotations

from pydantic import BaseModel, EmailStr

from backend.schemas.user_schema import UserRead


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead
