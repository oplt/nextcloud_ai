from __future__ import annotations

from urllib.parse import urlparse

from backend.connectors.email.config import ImapConnectorConfig
from backend.connectors.email.imap_client import AsyncImapClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.connectors.nextcloud.client import AsyncNextcloudClient
from backend.connectors.nextcloud.config import NextcloudConnectorConfig
from backend.core.config import settings
from backend.core.exceptions import AuthorizationError, NotFoundError
from backend.core.security import connector_secret_cipher
from backend.db.models import Connector, User
from backend.db.repo.connector import ConnectorRepository
from backend.db.repo.user import UserRepository
from backend.schemas.connector_schema import (
    ConnectorCreate,
    ConnectorTestResponse,
    ConnectorUpdate,
)
from backend.services.authorization_service import (
    connector_is_manageable_by_identity,
    connector_is_visible_to_identity,
    normalize_role_name,
)
from backend.services.audit_service import AuditService


class ConnectorService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ConnectorRepository(session)
        self.user_repo = UserRepository(session)
        self.audit = AuditService(session)

    async def create_connector(
        self, payload: ConnectorCreate, actor: User
    ) -> Connector:
        owner_user_id = actor.id
        if payload.owner_user_id is not None and normalize_role_name_from_user(actor) == "admin":
            if await self.user_repo.get(payload.owner_user_id) is None:
                raise NotFoundError("Owner user not found")
            owner_user_id = payload.owner_user_id
        metadata = {}
        if payload.connector_type == "nextcloud":
            metadata["verify_tls"] = (
                settings.NEXTCLOUD_VERIFY_TLS
                if payload.verify_tls is None
                else payload.verify_tls
            )
        else:
            metadata.update(
                {
                    "verify_tls": True if payload.verify_tls is None else payload.verify_tls,
                    "port": payload.port,
                    "use_ssl": True if payload.use_ssl is None else payload.use_ssl,
                    "search_criteria": payload.search_criteria or "ALL",
                }
            )
        connector = Connector(
            connector_type=payload.connector_type,
            display_name=payload.display_name,
            base_url=_normalize_connector_base_url(
                payload.base_url, connector_type=payload.connector_type
            ),
            username=payload.username,
            encrypted_secret=connector_secret_cipher.encrypt(payload.secret),
            root_path=payload.root_path,
            status="pending",
            metadata_json=metadata,
            owner_user_id=owner_user_id,
        )
        await self.repo.add(connector, flush=True)
        await self.audit.log(
            action="connector.created",
            resource_type="connector",
            resource_id=str(connector.id),
            message=f"{connector.connector_type.upper()} connector created",
            user=actor,
        )
        await self.session.commit()
        await self.session.refresh(connector)
        return connector

    async def update_connector(
        self, connector_id: str, payload: ConnectorUpdate, actor: User
    ) -> Connector:
        connector = await self.repo.get(connector_id)
        if connector is None:
            raise NotFoundError("Connector not found")
        actor_auth = _user_to_auth(actor)
        if not connector_is_manageable_by_identity(
            connector, auth=actor_auth, user=actor
        ):
            raise AuthorizationError("Connector is not assigned to you")

        data = payload.model_dump(exclude_unset=True)
        if "secret" in data and data["secret"]:
            connector.encrypted_secret = connector_secret_cipher.encrypt(
                data.pop("secret")
            )
        connector_type = connector.connector_type or "nextcloud"
        metadata = dict(connector.metadata_json or {})
        for key in ("verify_tls", "port", "use_ssl", "search_criteria"):
            if key in data:
                metadata[key] = data.pop(key)
        if metadata:
            connector.metadata_json = metadata
        if "owner_user_id" in data and normalize_role_name_from_user(actor) != "admin":
            data.pop("owner_user_id")
        elif "owner_user_id" in data and data["owner_user_id"] is not None:
            if await self.user_repo.get(data["owner_user_id"]) is None:
                raise NotFoundError("Owner user not found")
        if "base_url" in data and data["base_url"]:
            data["base_url"] = _normalize_connector_base_url(
                str(data["base_url"]), connector_type=connector_type
            )
        for key, value in data.items():
            setattr(connector, key, value)

        await self.audit.log(
            action="connector.updated",
            resource_type="connector",
            resource_id=str(connector.id),
            message="Connector updated",
            user=actor,
        )
        await self.session.commit()
        await self.session.refresh(connector)
        return connector

    async def get_connector(self, connector_id: str) -> Connector:
        connector = await self.repo.get(connector_id)
        if connector is None:
            raise NotFoundError("Connector not found")
        return connector

    async def get_connector_for_actor(
        self, connector_id: str, *, actor: User, write: bool = False
    ) -> Connector:
        connector = await self.get_connector(connector_id)
        actor_auth = _user_to_auth(actor)
        allowed = (
            connector_is_manageable_by_identity(connector, auth=actor_auth, user=actor)
            if write
            else connector_is_visible_to_identity(connector, auth=actor_auth, user=actor)
        )
        if not allowed:
            raise AuthorizationError("Connector is not assigned to you")
        return connector

    async def list_connectors_for_actor(self, actor: User) -> list[Connector]:
        if normalize_role_name_from_user(actor) == "admin":
            return await self.repo.list(limit=100, order_by=Connector.created_at.desc())
        return await self.repo.list_visible_to_user(user_id=str(actor.id), limit=100)

    async def delete_connector(self, connector_id: str, actor: User) -> None:
        connector = await self.get_connector_for_actor(
            connector_id, actor=actor, write=True
        )
        await self.repo.delete(connector)
        await self.audit.log(
            action="connector.deleted",
            resource_type="connector",
            resource_id=str(connector.id),
            message="Connector deleted",
            user=actor,
        )
        await self.session.commit()

    async def test_connector(self, connector: Connector) -> ConnectorTestResponse:
        if connector.connector_type == "imap":
            client = AsyncImapClient(self.build_imap_config(connector))
            try:
                await client.verify_credentials()
            finally:
                await client.aclose()
            return ConnectorTestResponse(ok=True, message="IMAP credentials verified")

        client = AsyncNextcloudClient(self.build_nextcloud_config(connector))
        try:
            await client.verify_credentials()
        finally:
            await client.aclose()
        return ConnectorTestResponse(ok=True, message="Nextcloud credentials verified")

    def build_config(self, connector: Connector) -> NextcloudConnectorConfig:
        return self.build_nextcloud_config(connector)

    def build_nextcloud_config(self, connector: Connector) -> NextcloudConnectorConfig:
        if connector.connector_type != "nextcloud":
            raise ValueError("Connector is not a Nextcloud connector")
        metadata = connector.metadata_json or {}
        return NextcloudConnectorConfig(
            base_url=connector.base_url,
            username=connector.username,
            app_password=connector_secret_cipher.decrypt(connector.encrypted_secret),
            root_path=connector.root_path,
            verify_tls=bool(metadata.get("verify_tls", settings.NEXTCLOUD_VERIFY_TLS)),
            request_timeout_seconds=settings.NEXTCLOUD_REQUEST_TIMEOUT_SECONDS,
        )

    def build_imap_config(self, connector: Connector) -> ImapConnectorConfig:
        if connector.connector_type != "imap":
            raise ValueError("Connector is not an IMAP connector")
        metadata = connector.metadata_json or {}
        parsed = urlparse(
            connector.base_url
            if "://" in connector.base_url
            else f"imaps://{connector.base_url}"
        )
        use_ssl = bool(metadata.get("use_ssl", True))
        default_port = 993 if use_ssl else 143
        return ImapConnectorConfig(
            host=parsed.hostname or connector.base_url,
            port=int(metadata.get("port") or parsed.port or default_port),
            username=connector.username,
            password=connector_secret_cipher.decrypt(connector.encrypted_secret),
            mailbox=connector.root_path or "INBOX",
            use_ssl=use_ssl,
            verify_tls=bool(metadata.get("verify_tls", True)),
            search_criteria=str(metadata.get("search_criteria") or "ALL"),
            fetch_limit=settings.EMAIL_CONNECTOR_FETCH_LIMIT,
        )


def _user_to_auth(user: User):
    from backend.core.security import AuthContext

    return AuthContext(
        user_id=str(user.id),
        auth_provider="local" if user.auth_provider == "local" else "nextcloud",
        external_subject=user.external_subject,
        username=user.username,
        email=user.email,
        display_name=user.full_name,
        is_superuser=user.is_superuser,
        role_name=user.role.name if user.role else None,
    )


def normalize_role_name_from_user(user: User) -> str:
    return normalize_role_name(_user_to_auth(user), user)


def _normalize_connector_base_url(base_url: str, *, connector_type: str) -> str:
    normalized = base_url.strip()
    if connector_type == "nextcloud":
        return normalized.rstrip("/")
    return normalized.rstrip("/")
