from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.connectors.nextcloud.schemas import Principal
from backend.core.exceptions import AuthenticationError, ConflictError
from backend.core.security import (
    AuthContext,
    app_token_service,
    get_password_hash,
    verify_password,
)
from backend.db.models import User
from backend.db.repo.user import RoleRepository, UserRepository
from backend.schemas.auth_schema import IssuedAuthSession
from backend.schemas.user_schema import UserRead
from backend.services.authorization_service import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER
from backend.services.audit_service import AuditService
from backend.services.role_bootstrap_service import RoleBootstrapService


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repo = UserRepository(session)
        self.role_repo = RoleRepository(session)
        self.audit = AuditService(session)
        self.role_bootstrap = RoleBootstrapService(session)

    async def login_with_password(
        self, email: str, password: str
    ) -> IssuedAuthSession:
        user = await self.user_repo.get_by_email(email)
        if (
            not user
            or not user.hashed_password
            or not verify_password(password, user.hashed_password)
        ):
            raise AuthenticationError(detail="Incorrect email or password")
        if not user.is_active:
            raise AuthenticationError(detail="Inactive user")
        return await self._issue_session_for_user(user, auth_provider="local")

    async def provision_local_user(
        self,
        *,
        email: str | None,
        username: str,
        password: str,
        full_name: str | None,
        role_id,
        is_superuser: bool,
    ) -> User:
        if email:
            existing = await self.user_repo.get_by_email(email)
            if existing:
                raise ConflictError("User already exists")
        roles = await self.role_bootstrap.ensure_system_roles()
        default_role_name = ROLE_ADMIN if is_superuser else ROLE_OPERATOR
        resolved_role_id = role_id
        if resolved_role_id is None:
            default_role = roles.get(default_role_name)
            resolved_role_id = default_role.id if default_role is not None else None
        user = User(
            auth_provider="local",
            username=username,
            email=email,
            hashed_password=get_password_hash(password),
            full_name=full_name,
            role_id=resolved_role_id,
            is_superuser=is_superuser,
            is_active=True,
        )
        await self.user_repo.add(user, flush=True)
        await self.audit.log(
            action="user.created",
            resource_type="user",
            resource_id=str(user.id),
            message="Local user provisioned",
            user=user,
        )
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def sync_nextcloud_principal(
        self, principal: Principal
    ) -> IssuedAuthSession:
        roles = await self.role_bootstrap.ensure_system_roles()
        user = await self.user_repo.get_by_external_subject("nextcloud", principal.sub)
        if user is None:
            viewer_role = roles.get(ROLE_VIEWER)
            user = User(
                auth_provider="nextcloud",
                external_subject=principal.sub,
                username=principal.username,
                email=principal.email,
                full_name=principal.display_name,
                nextcloud_base_url=principal.nc_base_url,
                role_id=viewer_role.id if viewer_role is not None else None,
                is_active=True,
            )
            await self.user_repo.add(user, flush=True)
        else:
            user.username = principal.username
            user.email = principal.email
            user.full_name = principal.display_name
            user.nextcloud_base_url = principal.nc_base_url
            if user.role_id is None:
                viewer_role = roles.get(ROLE_VIEWER)
                user.role_id = viewer_role.id if viewer_role is not None else None

        user.last_login_at = datetime.now(timezone.utc)
        await self.audit.log(
            action="auth.nextcloud_login",
            resource_type="user",
            resource_id=str(user.id),
            message="User authenticated through Nextcloud bridge",
            metadata={"groups": principal.groups, "external_subject": principal.sub},
            user=user,
        )
        await self.session.commit()
        await self.session.refresh(user)
        return await self._issue_session_for_user(
            user,
            auth_provider="nextcloud",
            external_subject=principal.sub,
            username=principal.username,
            groups=principal.groups,
            nextcloud_base_url=principal.nc_base_url,
        )

    async def _issue_session_for_user(
        self,
        user: User,
        *,
        auth_provider: str,
        external_subject: str | None = None,
        username: str | None = None,
        groups: list[str] | None = None,
        nextcloud_base_url: str | None = None,
    ) -> IssuedAuthSession:
        context = AuthContext(
            user_id=str(user.id),
            auth_provider=auth_provider,  # type: ignore[arg-type]
            external_subject=external_subject,
            username=username or user.username,
            display_name=user.full_name,
            email=user.email,
            groups=groups or [],
            nextcloud_base_url=nextcloud_base_url or user.nextcloud_base_url,
            is_superuser=user.is_superuser,
            role_name=user.role.name if user.role else None,
        )
        token, expires_in = app_token_service.issue_access_token(context)
        return IssuedAuthSession(
            access_token=token,
            expires_in=expires_in,
            user=UserRead.model_validate(user),
        )
