from backend.core.security import AuthContext, auth_user_identifiers
from backend.services.authorization_service import document_is_visible_to_auth


def _auth() -> AuthContext:
    return AuthContext(
        user_id="local-user-id",
        auth_provider="local",
        external_subject=None,
        username="nextcloud-user",
        email="user@example.com",
    )


def test_auth_user_identifiers_include_username_for_nextcloud_acl() -> None:
    assert auth_user_identifiers(_auth()) == [
        "local-user-id",
        "nextcloud-user",
        "user@example.com",
    ]


def test_document_visible_when_nextcloud_acl_matches_username() -> None:
    assert document_is_visible_to_auth(
        _auth(),
        owner_external_id=None,
        allowed_user_ids=["nextcloud-user"],
        allowed_group_ids=[],
        public_link_enabled=False,
        is_deleted=False,
    )


def test_document_visible_when_owner_matches_username() -> None:
    assert document_is_visible_to_auth(
        _auth(),
        owner_external_id="nextcloud-user",
        allowed_user_ids=[],
        allowed_group_ids=[],
        public_link_enabled=False,
        is_deleted=False,
    )
