from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.connectors.nextcloud.client import AsyncNextcloudClient
from backend.connectors.nextcloud.config import NextcloudConnectorConfig
from backend.core.config import settings
from backend.core.exceptions import NotFoundError
from backend.core.security import connector_secret_cipher
from backend.db.models import Connector, User
from backend.db.repo.connector import ConnectorRepository
from backend.schemas.connector_schema import (
    ConnectorCreate,
    ConnectorTestResponse,
    ConnectorUpdate,
)
from backend.services.audit_service import AuditService


class ConnectorService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ConnectorRepository(session)
        self.audit = AuditService(session)

    async def create_connector(
        self, payload: ConnectorCreate, actor: User
    ) -> Connector:
        connector = Connector(
            connector_type="nextcloud",
            display_name=payload.display_name,
            base_url=payload.base_url.rstrip("/"),
            username=payload.username,
            encrypted_secret=connector_secret_cipher.encrypt(payload.secret),
            root_path=payload.root_path,
            status="pending",
            metadata_json={
                "verify_tls": settings.NEXTCLOUD_VERIFY_TLS
                if payload.verify_tls is None
                else payload.verify_tls
            },
        )
        await self.repo.add(connector, flush=True)
        await self.audit.log(
            action="connector.created",
            resource_type="connector",
            resource_id=str(connector.id),
            message="Nextcloud connector created",
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

        data = payload.model_dump(exclude_unset=True)
        if "secret" in data and data["secret"]:
            connector.encrypted_secret = connector_secret_cipher.encrypt(
                data.pop("secret")
            )
        if "verify_tls" in data:
            metadata = dict(connector.metadata_json or {})
            metadata["verify_tls"] = data.pop("verify_tls")
            connector.metadata_json = metadata
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

    async def delete_connector(self, connector_id: str, actor: User) -> None:
        connector = await self.get_connector(connector_id)
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
        client = AsyncNextcloudClient(self.build_config(connector))
        try:
            await client.verify_credentials()
        finally:
            await client.aclose()
        return ConnectorTestResponse(ok=True, message="Nextcloud credentials verified")

    def build_config(self, connector: Connector) -> NextcloudConnectorConfig:
        metadata = connector.metadata_json or {}
        return NextcloudConnectorConfig(
            base_url=connector.base_url,
            username=connector.username,
            app_password=connector_secret_cipher.decrypt(connector.encrypted_secret),
            root_path=connector.root_path,
            verify_tls=bool(metadata.get("verify_tls", settings.NEXTCLOUD_VERIFY_TLS)),
            request_timeout_seconds=settings.NEXTCLOUD_REQUEST_TIMEOUT_SECONDS,
        )
