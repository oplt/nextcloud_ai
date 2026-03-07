from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.deps import CurrentUserDep, DbSessionDep, SuperUserDep
from backend.core.security import get_password_hash
from backend.db.models import User
from backend.db.repo.user import UserRepository
from backend.schemas.user_schema import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/", response_model=UserRead)
async def create_user(
        payload: UserCreate,
        session: DbSessionDep,
        _: SuperUserDep,
):
    repo = UserRepository(session)

    existing = await repo.get_by_email(payload.email)
    if existing:
        raise ValueError("User already exists")

    user = User(
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name,
        role_id=payload.role_id,
        is_active=True,
    )

    await repo.add(user)
    await session.commit()
    await session.refresh(user)

    return UserRead.model_validate(user)


@router.get("/", response_model=list[UserRead])
async def list_users(
        session: DbSessionDep,
        _: CurrentUserDep,
):
    repo = UserRepository(session)
    users = await repo.list(limit=100)
    return [UserRead.model_validate(u) for u in users]


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
        user_id: str,
        session: DbSessionDep,
        _: CurrentUserDep,
):
    repo = UserRepository(session)
    user = await repo.get(user_id)

    if not user:
        raise ValueError("User not found")

    return UserRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
        user_id: str,
        payload: UserUpdate,
        session: DbSessionDep,
        _: SuperUserDep,
):
    repo = UserRepository(session)
    user = await repo.get(user_id)

    if not user:
        raise ValueError("User not found")

    data = payload.model_dump(exclude_unset=True)

    for key, value in data.items():
        setattr(user, key, value)

    await session.commit()
    await session.refresh(user)

    return UserRead.model_validate(user)