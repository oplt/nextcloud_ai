from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..db.models import Document


def build_chunk_metadata(
    *,
    document: Document,
    chunk_index: int,
    page_number: int | None,
    section_title: str | None,
    base_metadata: dict[str, object] | None = None,
) -> dict[str, Any]:
    document_meta = dict(document.metadata_json or {})
    now = datetime.now(timezone.utc).isoformat()
    tenant_id = str(document_meta.get("tenant_id") or document.connector_id)
    project_id = str(document_meta.get("project_id") or document.connector_id)
    permission_scope = _permission_scope(document)

    return {
        **dict(base_metadata or {}),
        "tenant_id": tenant_id,
        "project_id": project_id,
        "document_id": str(document.id),
        "document_title": str(document_meta.get("title") or document.file_name),
        "file_path": document.file_path,
        "page_number": page_number,
        "section_title": section_title,
        "chunk_index": chunk_index,
        "created_at": now,
        "updated_at": now,
        "permission_scope": permission_scope,
    }


def _permission_scope(document: Document) -> str:
    scopes: list[str] = []
    if document.public_link_enabled:
        scopes.append("public_link")
    if document.owner_external_id:
        scopes.append("owner")
    if document.allowed_user_ids:
        scopes.append("users")
    if document.allowed_group_ids:
        scopes.append("groups")
    return ",".join(scopes) if scopes else "private"

