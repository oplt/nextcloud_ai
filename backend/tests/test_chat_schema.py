from __future__ import annotations

from uuid import uuid4

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
    )

    payload = response.model_dump(mode="json")
    assert payload["session_id"] == str(session_id)
    assert payload["sources"][0]["file_name"] == "leave.md"
