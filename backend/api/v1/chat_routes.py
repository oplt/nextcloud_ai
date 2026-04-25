from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from ..deps import AuthenticatedUser, DbSessionDep, permission_required
from ...core.exceptions import NotFoundError
from ...db.repo.chat import ChatSessionRepository
from ...schemas.chat_schema import (
    ChatAskRequest,
    ChatAskResponse,
    ChatMemoryPatchRequest,
    ChatSessionDetail,
    ChatSessionRead,
)
from ...services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/ask", response_model=ChatAskResponse)
async def ask_question(
    payload: ChatAskRequest,
    session: DbSessionDep,
    identity: AuthenticatedUser = Depends(permission_required("chat:use")),
) -> ChatAskResponse:
    return await ChatService(session).ask(
        user=identity.user, auth=identity.auth, request=payload
    )


@router.get("/sessions", response_model=list[ChatSessionRead])
async def list_chat_sessions(
    session: DbSessionDep,
    identity: AuthenticatedUser = Depends(permission_required("chat:use")),
) -> list[ChatSessionRead]:
    items = await ChatSessionRepository(session).list_by_user(
        identity.user.id, limit=100
    )
    return [ChatSessionRead.model_validate(item) for item in items]


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
async def get_chat_session(
    session_id: str,
    session: DbSessionDep,
    identity: AuthenticatedUser = Depends(permission_required("chat:use")),
) -> ChatSessionDetail:
    item = await ChatSessionRepository(session).get_with_messages(session_id)
    if item is None or item.user_id != identity.user.id:
        raise NotFoundError("Chat session not found")
    return ChatSessionDetail.model_validate(item)


@router.patch("/sessions/{session_id}/memory", response_model=dict)
async def patch_chat_session_memory(
    session_id: str,
    payload: ChatMemoryPatchRequest,
    session: DbSessionDep,
    identity: AuthenticatedUser = Depends(permission_required("chat:use")),
) -> dict:
    return await ChatService(session).patch_session_memory(
        user=identity.user, session_id=session_id, payload=payload
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(
    session_id: str,
    session: DbSessionDep,
    identity: AuthenticatedUser = Depends(permission_required("chat:use")),
) -> Response:
    await ChatService(session).delete_session(session_id, actor=identity.user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
