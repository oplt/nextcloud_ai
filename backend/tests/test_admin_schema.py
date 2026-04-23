from __future__ import annotations

from datetime import datetime, UTC
from uuid import uuid4

from backend.schemas.admin_schema import AuditLogRead


def test_audit_log_read_accepts_uuid_user_id() -> None:
    now = datetime.now(UTC)
    user_id = uuid4()

    payload = AuditLogRead.model_validate(
        {
            "id": uuid4(),
            "created_at": now,
            "updated_at": now,
            "user_id": user_id,
            "action": "audit.read",
            "resource_type": "audit_log",
            "resource_id": None,
            "message": "Loaded audit log page",
            "metadata_json": None,
            "user": None,
        }
    )

    assert payload.user_id == user_id
