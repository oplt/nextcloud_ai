from __future__ import annotations

from backend.core.security import AuthContext
from backend.services.authorization_service import document_is_visible_to_auth


def test_document_visibility_allows_group_match() -> None:
    auth = AuthContext(
        user_id='1',
        auth_provider='nextcloud',
        external_subject='alice',
        username='alice',
        groups=['finance', 'staff'],
    )

    assert document_is_visible_to_auth(
        auth,
        owner_external_id='bob',
        allowed_user_ids=['charlie'],
        allowed_group_ids=['staff'],
        public_link_enabled=False,
        is_deleted=False,
    )


def test_document_visibility_rejects_deleted_documents() -> None:
    auth = AuthContext(user_id='1', auth_provider='local', username='admin', is_superuser=True)

    assert not document_is_visible_to_auth(
        auth,
        owner_external_id=None,
        allowed_user_ids=[],
        allowed_group_ids=[],
        public_link_enabled=True,
        is_deleted=True,
    )
