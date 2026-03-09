from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import select

from backend.core.security import AuthContext
from backend.db.models import Document
from backend.db.repo.document import DocumentRepository
from backend.services.authorization_service import document_is_visible_to_auth


def test_document_visibility_allows_group_match() -> None:
    auth = AuthContext(
        user_id="1",
        auth_provider="nextcloud",
        external_subject="alice",
        username="alice",
        groups=["finance", "staff"],
    )

    assert document_is_visible_to_auth(
        auth,
        owner_external_id="bob",
        allowed_user_ids=["charlie"],
        allowed_group_ids=["staff"],
        public_link_enabled=False,
        is_deleted=False,
    )


def test_document_visibility_rejects_deleted_documents() -> None:
    auth = AuthContext(
        user_id="1", auth_provider="local", username="admin", is_superuser=True
    )

    assert not document_is_visible_to_auth(
        auth,
        owner_external_id=None,
        allowed_user_ids=[],
        allowed_group_ids=[],
        public_link_enabled=True,
        is_deleted=True,
    )


def test_document_visibility_clause_compiles_postgres_overlap_filters() -> None:
    auth = AuthContext(
        user_id="1",
        auth_provider="nextcloud",
        external_subject="alice",
        username="alice",
        groups=["finance", "staff"],
    )

    stmt = select(Document).where(DocumentRepository.visibility_clause(auth))
    compiled = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "&&" in compiled
    assert "allowed_user_ids" in compiled
    assert "allowed_group_ids" in compiled
