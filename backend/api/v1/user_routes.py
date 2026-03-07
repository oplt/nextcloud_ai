from __future__ import annotations

from fastapi import APIRouter

from backend.api.deps import CurrentIdentityDep, DbSessionDep, SuperUserDep
from backend.core.exceptions import NotFoundError
from backend.db.repo.user import UserRepository
from backend.schemas.user_schema import UserCreate, UserRead, UserUpdate
from backend.services.auth_service import AuthService

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/", response_model=UserRead)
async def create_user(payload: UserCreate, session: DbSessionDep, superuser: SuperUserDep) -> UserRead:
    user = await AuthService(session).provision_local_user(
        email=payload.email,
        username=payload.username,
        password=payload.password,
        full_name=payload.full_name,
        role_id=payload.role_id,
        is_superuser=payload.is_superuser,
    )
    return UserRead.model_validate(user)


@router.get("/", response_model=list[UserRead])
async def list_users(session: DbSessionDep, _: CurrentIdentityDep) -> list[UserRead]:
    users = await UserRepository(session).search(limit=100)
    return [UserRead.model_validate(user) for user in users]


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: str, session: DbSessionDep, _: CurrentIdentityDep) -> UserRead:
    user = await UserRepository(session).get(user_id)
    if user is None:
        raise NotFoundError("User not found")
    return UserRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(user_id: str, payload: UserUpdate, session: DbSessionDep, _: SuperUserDep) -> UserRead:
    repo = UserRepository(session)
    user = await repo.get(user_id)
    if user is None:
        raise NotFoundError("User not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    await session.commit()
    await session.refresh(user)
    return UserRead.model_validate(user)
