from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.api.deps import AuthenticatedUser, get_current_identity
from backend.core.security import AuthContext
from backend.db.models import User
from backend.main import app
from backend.schemas.chat_schema import ChatAskResponse


class FakeChatService:
    def __init__(self, _session: object) -> None:
        self.session = _session

    async def ask(self, **_kwargs: object) -> ChatAskResponse:
        sid = uuid4()
        uid = uuid4()
        aid = uuid4()
        return ChatAskResponse(
            session_id=sid,
            answer='ok',
            sources=[],
            user_message_id=uid,
            assistant_message_id=aid,
            parent_message_id=None,
            request_id='req-1',
            cited_sources=[],
            active_context_document_ids=[],
            active_context_documents=[],
            conversation_query='conv',
            generation_trace_id='req-1',
            llm_provider='stub',
            llm_model_id='stub',
            grounded_prompt_version='1',
            retrieval_settings={},
            verification=None,
        )


@pytest.fixture
def chat_ask_client(monkeypatch: pytest.MonkeyPatch):
    user = User(
        id=uuid4(),
        auth_provider='local',
        username='tuser',
        email='t@test.com',
        is_active=True,
        is_superuser=True,
    )

    async def override_identity() -> AuthenticatedUser:
        return AuthenticatedUser(
            user=user,
            auth=AuthContext(
                user_id=str(user.id),
                auth_provider='local',
                username=user.username,
                is_superuser=True,
                role_name='admin',
            ),
        )

    app.dependency_overrides[get_current_identity] = override_identity
    monkeypatch.setattr('backend.api.v1.chat_routes.ChatService', FakeChatService)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_post_chat_ask_returns_generation_metadata(chat_ask_client: TestClient) -> None:
    csrf = chat_ask_client.get('/api/v1/auth/csrf').json()['csrf_token']
    chat_ask_client.headers.update({'X-CSRF-Token': csrf})
    res = chat_ask_client.post('/api/v1/chat/ask', json={'question': 'Hello world'})
    assert res.status_code == 200
    data = res.json()
    assert data['answer'] == 'ok'
    assert data['generation_trace_id'] == 'req-1'
    assert data['llm_provider'] == 'stub'
    assert data['grounded_prompt_version'] == '1'
    assert 'assistant_message_id' in data
