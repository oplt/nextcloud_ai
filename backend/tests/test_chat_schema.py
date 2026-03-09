from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from backend.db.models import ChatMessage, ChatSession
from backend.schemas.chat_schema import ChatAskResponse


def test_chat_response_schema_round_trip() -> None:
    session_id = uuid4()
    response = ChatAskResponse(
        session_id=session_id,
        answer="The handbook says employees receive 25 days of leave. [1]",
        sources=[
            {
                "chunk_id": uuid4(),
                "document_id": uuid4(),
                "file_name": "leave.md",
                "file_path": "/policies/leave.md",
                "page_number": None,
                "section_title": "Annual Leave",
                "snippet": "Employees receive 25 days of leave.",
                "distance": 0.2,
                "score": 0.9,
            }
        ],
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        parent_message_id=None,
        request_id=None,
        cited_sources=[
            {
                "chunk_id": uuid4(),
                "document_id": uuid4(),
                "file_name": "leave.md",
                "file_path": "/policies/leave.md",
                "page_number": None,
                "section_title": "Annual Leave",
                "snippet": "Employees receive 25 days of leave.",
                "distance": 0.2,
                "score": 0.9,
            }
        ],
        active_context_document_ids=[],
        active_context_documents=[],
        conversation_query="employees leave handbook",
    )

    payload = response.model_dump(mode="json")
    assert payload["session_id"] == str(session_id)
    assert payload["sources"][0]["file_name"] == "leave.md"


def test_chat_session_subject_uses_latest_message_content() -> None:
    session = ChatSession(
        id=uuid4(),
        user_id=uuid4(),
        title="Original title",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.messages = [
        ChatMessage(
            id=uuid4(),
            session_id=session.id,
            role="user",
            content="First question",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
        ChatMessage(
            id=uuid4(),
            session_id=session.id,
            role="assistant",
            content="Latest   answer\nwith extra whitespace",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
    ]

    assert session.subject == "Latest answer with extra whitespace"
