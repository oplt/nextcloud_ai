from __future__ import annotations

from fastapi import APIRouter

from backend.api.deps import CurrentIdentityDep, DbSessionDep
from backend.schemas.connector_schema import ConnectorCreate, ConnectorRead, ConnectorSyncRequest, ConnectorTestResponse, ConnectorUpdate
from backend.schemas.job_schema import SyncJobRead
from backend.services.connector_service import ConnectorService
from backend.services.job_service import JobService
from backend.workers.indexing_tasks import enqueue_connector_sync_job

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.post("/", response_model=ConnectorRead)
async def create_connector(payload: ConnectorCreate, session: DbSessionDep, identity: CurrentIdentityDep) -> ConnectorRead:
    connector = await ConnectorService(session).create_connector(payload, actor=identity.user)
    return ConnectorRead.model_validate(connector)


@router.get("/", response_model=list[ConnectorRead])
async def list_connectors(session: DbSessionDep, _: CurrentIdentityDep) -> list[ConnectorRead]:
    connectors = await ConnectorService(session).repo.list(limit=100, order_by=None)
    return [ConnectorRead.model_validate(connector) for connector in connectors]


@router.get("/{connector_id}", response_model=ConnectorRead)
async def get_connector(connector_id: str, session: DbSessionDep, _: CurrentIdentityDep) -> ConnectorRead:
    connector = await ConnectorService(session).get_connector(connector_id)
    return ConnectorRead.model_validate(connector)


@router.patch("/{connector_id}", response_model=ConnectorRead)
async def update_connector(connector_id: str, payload: ConnectorUpdate, session: DbSessionDep, identity: CurrentIdentityDep) -> ConnectorRead:
    connector = await ConnectorService(session).update_connector(connector_id, payload, actor=identity.user)
    return ConnectorRead.model_validate(connector)


@router.post("/{connector_id}/test", response_model=ConnectorTestResponse)
async def test_connector(connector_id: str, session: DbSessionDep, _: CurrentIdentityDep) -> ConnectorTestResponse:
    service = ConnectorService(session)
    connector = await service.get_connector(connector_id)
    return await service.test_connector(connector)


@router.post("/{connector_id}/sync", response_model=SyncJobRead)
async def sync_connector(
    connector_id: str,
    payload: ConnectorSyncRequest,
    session: DbSessionDep,
    identity: CurrentIdentityDep,
) -> SyncJobRead:
    job_service = JobService(session)
    job = await job_service.create_sync_job(
        connector_id=connector_id,
        requested_by=identity.user,
        full_reindex=payload.full_reindex,
    )
    task = enqueue_connector_sync_job(str(job.id))
    job.worker_task_id = task.id
    await session.commit()
    await session.refresh(job)
    return SyncJobRead.model_validate(job)
