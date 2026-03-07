from __future__ import annotations

from fastapi import APIRouter

from backend.api.deps import CurrentUserDep, DbSessionDep
from backend.db.models import Connector
from backend.db.repo.connector import ConnectorRepository
from backend.schemas.connector_schema import (
    ConnectorCreate,
    ConnectorRead,
    ConnectorUpdate,
)

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.post("/", response_model=ConnectorRead)
async def create_connector(
    payload: ConnectorCreate,
    session: DbSessionDep,
    _: CurrentUserDep,
):
    repo = ConnectorRepository(session)

    connector = Connector(
        display_name=payload.display_name,
        base_url=payload.base_url,
        username=payload.username,
        encrypted_secret=payload.secret,
        root_path=payload.root_path,
    )

    await repo.add(connector)
    await session.commit()
    await session.refresh(connector)

    return ConnectorRead.model_validate(connector)


@router.get("/", response_model=list[ConnectorRead])
async def list_connectors(
        session: DbSessionDep,
        _: CurrentUserDep,
):
    repo = ConnectorRepository(session)
    connectors = await repo.list(limit=100)

    return [ConnectorRead.model_validate(c) for c in connectors]


@router.patch("/{connector_id}", response_model=ConnectorRead)
async def update_connector(
        connector_id: str,
        payload: ConnectorUpdate,
        session: DbSessionDep,
        _: CurrentUserDep,
):
    repo = ConnectorRepository(session)
    connector = await repo.get(connector_id)

    if not connector:
        raise ValueError("Connector not found")

    data = payload.model_dump(exclude_unset=True)

    for key, value in data.items():
        setattr(connector, key, value)

    await session.commit()
    await session.refresh(connector)

    return ConnectorRead.model_validate(connector)