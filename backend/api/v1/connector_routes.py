from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from ..deps import AuthenticatedUser, DbSessionDep, permission_required
from ...connectors.nextcloud.exceptions import (
    NextcloudAPIError,
    NextcloudAuthenticationError,
)
from ...core.exceptions import BadRequestError
from ...schemas.connector_schema import (
    ConnectorCreate,
    ConnectorRead,
    ConnectorSyncRequest,
    ConnectorTestResponse,
    ConnectorUpdate,
)
from ...schemas.job_schema import SyncJobRead
from ...services.connector_service import ConnectorService
from ...services.job_service import JobService
from ...workers.indexing_tasks import (
    enqueue_connector_sync_job,
    should_execute_tasks_locally,
)

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.post("", response_model=ConnectorRead)
async def create_connector(
        payload: ConnectorCreate,
        session: DbSessionDep,
        identity: AuthenticatedUser = Depends(permission_required("connectors:create")),
) -> ConnectorRead:
    connector = await ConnectorService(session).create_connector(
        payload, actor=identity.user
    )
    return ConnectorRead.model_validate(connector)


@router.get("", response_model=list[ConnectorRead])
async def list_connectors(
        session: DbSessionDep,
        identity: AuthenticatedUser = Depends(permission_required("connectors:read")),
) -> list[ConnectorRead]:
    connectors = await ConnectorService(session).list_connectors_for_actor(identity.user)
    return [ConnectorRead.model_validate(connector) for connector in connectors]


@router.get("/{connector_id}", response_model=ConnectorRead)
async def get_connector(
        connector_id: str,
        session: DbSessionDep,
        identity: AuthenticatedUser = Depends(permission_required("connectors:read")),
) -> ConnectorRead:
    connector = await ConnectorService(session).get_connector_for_actor(
        connector_id, actor=identity.user
    )
    return ConnectorRead.model_validate(connector)


@router.patch("/{connector_id}", response_model=ConnectorRead)
async def update_connector(
        connector_id: str,
        payload: ConnectorUpdate,
        session: DbSessionDep,
        identity: AuthenticatedUser = Depends(permission_required("connectors:update_owned")),
) -> ConnectorRead:
    connector = await ConnectorService(session).update_connector(
        connector_id, payload, actor=identity.user
    )
    return ConnectorRead.model_validate(connector)


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(
        connector_id: str,
        session: DbSessionDep,
        identity: AuthenticatedUser = Depends(permission_required("connectors:delete_owned")),
) -> Response:
    await ConnectorService(session).delete_connector(connector_id, actor=identity.user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{connector_id}/test", response_model=ConnectorTestResponse)
async def test_connector(
        connector_id: str,
        session: DbSessionDep,
        identity: AuthenticatedUser = Depends(permission_required("connectors:test")),
) -> ConnectorTestResponse:
    service = ConnectorService(session)
    connector = await service.get_connector_for_actor(
        connector_id, actor=identity.user, write=True
    )
    try:
        return await service.test_connector(connector)
    except NextcloudAuthenticationError as exc:
        raise BadRequestError(
            "Nextcloud rejected the connector credentials. Use the account username and an app password."
        ) from exc
    except NextcloudAPIError as exc:
        raise BadRequestError(str(exc)) from exc


@router.post("/{connector_id}/sync", response_model=SyncJobRead)
async def sync_connector(
        connector_id: str,
        payload: ConnectorSyncRequest,
        session: DbSessionDep,
        identity: AuthenticatedUser = Depends(permission_required("connectors:sync_owned")),
) -> SyncJobRead:
    await ConnectorService(session).get_connector_for_actor(
        connector_id, actor=identity.user, write=True
    )
    job_service = JobService(session)
    latest_job = await job_service.repo.get_latest_for_connector(connector_id)
    if latest_job is not None and latest_job.status == "running":
        return SyncJobRead.model_validate(latest_job)
    if latest_job is not None and latest_job.status == "queued":
        if should_execute_tasks_locally():
            task = enqueue_connector_sync_job(str(latest_job.id))
            latest_job.worker_task_id = task.id
            await session.commit()
            await session.refresh(latest_job)
        return SyncJobRead.model_validate(latest_job)

    job = await job_service.create_sync_job(
        connector_id=connector_id,
        requested_by=identity.user,
        full_reindex=payload.full_reindex,
        job_key=(
            f"manual:{connector_id}:{payload.idempotency_key}"
            if payload.idempotency_key
            else None
        ),
    )
    task = enqueue_connector_sync_job(str(job.id))
    job.worker_task_id = task.id
    await session.commit()
    await session.refresh(job)
    return SyncJobRead.model_validate(job)
