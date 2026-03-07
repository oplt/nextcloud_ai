from __future__ import annotations

from fastapi import APIRouter

from backend.api.deps import CurrentUserDep, DbSessionDep
from backend.db.repo.chat import ChatSessionRepository
from backend.schemas.chat_schema import ChatAskRequest, ChatAskResponse, ChatSessionRead
from backend.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/ask", response_model=ChatAskResponse)
async def ask_question(
    payload: ChatAskRequest,
    session: DbSessionDep,
    current_user: CurrentUserDep,
) -> ChatAskResponse:
    service = ChatService(session)
    return await service.ask(user=current_user, request=payload)


@router.get("/sessions", response_model=list[ChatSessionRead])
async def list_chat_sessions(
    session: DbSessionDep,
    current_user: CurrentUserDep,
) -> list[ChatSessionRead]:
    repo = ChatSessionRepository(session)
    items = await repo.list_by_user(current_user.id, limit=100)
    return [ChatSessionRead.model_validate(item) for item in items]