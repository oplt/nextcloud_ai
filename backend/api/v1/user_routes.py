from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import AuthenticatedUser, DbSessionDep, permission_required
from ...core.exceptions import NotFoundError
from ...db.repo.user import RoleRepository, UserRepository
from ...schemas.user_schema import UserCreate, UserRead, UserUpdate
from ...services.audit_service import AuditService
from ...services.auth_service import AuthService

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/", response_model=UserRead)
async def create_user(
    payload: UserCreate,
    session: DbSessionDep,
    identity: AuthenticatedUser = Depends(permission_required("users:write")),
) -> UserRead:
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
async def list_users(
    session: DbSessionDep,
    query: str | None = Query(default=None),
    _: AuthenticatedUser = Depends(permission_required("users:read")),
) -> list[UserRead]:
    users = await UserRepository(session).search(query=query, limit=100)
    return [UserRead.model_validate(user) for user in users]


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: str,
    session: DbSessionDep,
    _: AuthenticatedUser = Depends(permission_required("users:read")),
) -> UserRead:
    user = await UserRepository(session).get(user_id)
    if user is None:
        raise NotFoundError("User not found")
    return UserRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: str,
    payload: UserUpdate,
    session: DbSessionDep,
    identity: AuthenticatedUser = Depends(permission_required("users:write")),
) -> UserRead:
    repo = UserRepository(session)
    role_repo = RoleRepository(session)
    user = await repo.get(user_id)
    if user is None:
        raise NotFoundError("User not found")
    changes = payload.model_dump(exclude_unset=True)
    if "role_id" in changes and changes["role_id"] is not None:
        role = await role_repo.get(changes["role_id"])
        if role is None:
            raise NotFoundError("Role not found")
    for key, value in changes.items():
        setattr(user, key, value)
    await AuditService(session).log(
        action="user.updated",
        resource_type="user",
        resource_id=str(user.id),
        message="User profile updated",
        user=identity.user,
    )
    await session.commit()
    await session.refresh(user)
    return UserRead.model_validate(user)
