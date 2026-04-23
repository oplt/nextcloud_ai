from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from backend.db.models import ChatMessage, ChatSession
from backend.schemas.chat_schema import ChatAskResponse, ChatSessionDetail


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
        generation_trace_id="trace-test",
        llm_provider="stub",
        llm_model_id="stub",
        grounded_prompt_version="1",
        retrieval_settings={"top_k": 6},
        verification={"result": "passed"},
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


def test_chat_session_detail_exposes_active_context_from_latest_assistant_citations() -> None:
    session = ChatSession(
        id=uuid4(),
        user_id=uuid4(),
        title="Employment thread",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.messages = [
        ChatMessage(
            id=uuid4(),
            session_id=session.id,
            role="user",
            content="Where did Ozgur work in 2009?",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
        ChatMessage(
            id=uuid4(),
            session_id=session.id,
            role="assistant",
            content="He worked at Turkish Statistical Office [1].",
            citations_json=[
                {
                    "document_id": str(uuid4()),
                    "file_name": "old.pdf",
                    "file_path": "/docs/old.pdf",
                }
            ],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
        ChatMessage(
            id=uuid4(),
            session_id=session.id,
            role="assistant",
            content="After that, he worked at Ataturk University [1][2].",
            citations_json=[
                {
                    "document_id": str(uuid4()),
                    "file_name": "resume.pdf",
                    "file_path": "/docs/resume.pdf",
                },
                {
                    "document_id": str(uuid4()),
                    "file_name": "cv.pdf",
                    "file_path": "/docs/cv.pdf",
                },
            ],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
    ]

    detail = ChatSessionDetail.model_validate(session)

    assert len(detail.messages) == 3
    assert len(detail.active_context_document_ids) == 2
    assert detail.active_context_documents == [
        {
            "document_id": detail.active_context_document_ids[0],
            "file_name": "resume.pdf",
            "file_path": "/docs/resume.pdf",
        },
        {
            "document_id": detail.active_context_document_ids[1],
            "file_name": "cv.pdf",
            "file_path": "/docs/cv.pdf",
        },
    ]
