"""Phase 1B: ACL neighbors, public-link grants, webhook auth."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.connectors.nextcloud.identity import (
    namespace_local_user,
    namespace_nc_group,
    namespace_nc_user,
    share_has_read,
)
from backend.connectors.nextcloud.permissions import NextcloudPermissionService
from backend.connectors.nextcloud.schemas import ShareGrant
from backend.connectors.nextcloud.webhooks import _verify_secret
from backend.core.config import Settings
from backend.core.security import AuthContext, auth_acl_principals
from backend.services.authorization_service import document_is_visible_to_auth
from backend.services.chat_service import ChatService


def test_public_link_without_read_does_not_enable_global_access() -> None:
    service = NextcloudPermissionService(client=SimpleNamespace())  # type: ignore[arg-type]
    allowed_users: set[str] = set()
    allowed_groups: set[str] = set()
    unresolved: set[int] = set()
    share = ShareGrant(
        share_id="1",
        share_type=3,
        permissions=4,  # create only
        path="/file.txt",
        uid_owner="owner",
    )
    result = service._apply_share(
        share,
        allowed_users,
        allowed_groups,
        unresolved,
        instance_base_url="https://nc.example",
        now=datetime.now(timezone.utc),
    )
    assert result == "no_read"
    assert allowed_users == set()
    assert allowed_groups == set()


def test_public_open_read_link_does_not_enter_allowed_principals() -> None:
    service = NextcloudPermissionService(client=SimpleNamespace())  # type: ignore[arg-type]
    allowed_users: set[str] = set()
    allowed_groups: set[str] = set()
    unresolved: set[int] = set()
    share = ShareGrant(
        share_id="2",
        share_type=3,
        permissions=1,
        path="/file.txt",
        uid_owner="owner",
        password=None,
        expiration=None,
    )
    result = service._apply_share(
        share,
        allowed_users,
        allowed_groups,
        unresolved,
        instance_base_url="https://nc.example",
        now=datetime.now(timezone.utc),
    )
    assert result == "public_open_read"
    assert allowed_users == set()
    assert allowed_groups == set()


def test_password_protected_and_expired_public_links_ignored() -> None:
    service = NextcloudPermissionService(client=SimpleNamespace())  # type: ignore[arg-type]
    allowed_users: set[str] = set()
    allowed_groups: set[str] = set()
    unresolved: set[int] = set()
    protected = ShareGrant(
        share_id="3",
        share_type=3,
        permissions=1,
        path="/a",
        password="yes",
    )
    assert (
        service._apply_share(
            protected,
            allowed_users,
            allowed_groups,
            unresolved,
            instance_base_url="https://nc.example",
            now=datetime.now(timezone.utc),
        )
        == "public_ignored"
    )
    expired = ShareGrant(
        share_id="4",
        share_type=3,
        permissions=1,
        path="/b",
        expiration="2000-01-01",
    )
    assert (
        service._apply_share(
            expired,
            allowed_users,
            allowed_groups,
            unresolved,
            instance_base_url="https://nc.example",
            now=datetime.now(timezone.utc),
        )
        == "expired"
    )


def test_user_group_shares_are_namespaced_and_require_read() -> None:
    service = NextcloudPermissionService(client=SimpleNamespace())  # type: ignore[arg-type]
    allowed_users: set[str] = set()
    allowed_groups: set[str] = set()
    unresolved: set[int] = set()
    service._apply_share(
        ShareGrant(
            share_id="5",
            share_type=0,
            permissions=1,
            path="/x",
            share_with="alice",
        ),
        allowed_users,
        allowed_groups,
        unresolved,
        instance_base_url="https://nc.example/nextcloud",
        now=datetime.now(timezone.utc),
    )
    service._apply_share(
        ShareGrant(
            share_id="6",
            share_type=1,
            permissions=1,
            path="/x",
            share_with="finance",
        ),
        allowed_users,
        allowed_groups,
        unresolved,
        instance_base_url="https://nc.example/nextcloud",
        now=datetime.now(timezone.utc),
    )
    # Federated — fail closed.
    service._apply_share(
        ShareGrant(
            share_id="7",
            share_type=6,
            permissions=1,
            path="/x",
            share_with="bob@other",
        ),
        allowed_users,
        allowed_groups,
        unresolved,
        instance_base_url="https://nc.example/nextcloud",
        now=datetime.now(timezone.utc),
    )
    assert namespace_nc_user("https://nc.example/nextcloud", "alice") in allowed_users
    assert namespace_nc_group("https://nc.example/nextcloud", "finance") in allowed_groups
    assert 6 in unresolved
    assert "bob@other" not in allowed_groups


def test_local_user_does_not_match_nextcloud_bare_username() -> None:
    local = AuthContext(
        user_id=str(uuid4()),
        auth_provider="local",
        username="alice",
        is_superuser=False,
    )
    nc = AuthContext(
        user_id=str(uuid4()),
        auth_provider="nextcloud",
        username="alice",
        external_subject="alice",
        nextcloud_base_url="https://nc.example",
        is_superuser=False,
    )
    local_principals = set(auth_acl_principals(local))
    nc_principals = set(auth_acl_principals(nc))
    assert namespace_local_user("alice") in local_principals
    assert namespace_nc_user("https://nc.example", "alice") in nc_principals
    assert local_principals.isdisjoint(nc_principals - {local.user_id, nc.user_id})

    assert (
        document_is_visible_to_auth(
            local,
            owner_external_id=namespace_nc_user("https://nc.example", "alice"),
            allowed_user_ids=[namespace_nc_user("https://nc.example", "alice")],
            allowed_group_ids=[],
            public_link_enabled=True,
            is_deleted=False,
        )
        is False
    )
    assert (
        document_is_visible_to_auth(
            nc,
            owner_external_id=namespace_nc_user("https://nc.example", "alice"),
            allowed_user_ids=[namespace_nc_user("https://nc.example", "alice")],
            allowed_group_ids=[],
            public_link_enabled=True,
            is_deleted=False,
        )
        is True
    )
    # public_link_enabled must not grant visibility by itself.
    assert (
        document_is_visible_to_auth(
            local,
            owner_external_id=None,
            allowed_user_ids=[],
            allowed_group_ids=[],
            public_link_enabled=True,
            is_deleted=False,
        )
        is False
    )


def test_share_has_read_bit() -> None:
    assert share_has_read(1) is True
    assert share_has_read(4) is False
    assert share_has_read(5) is True


def test_webhook_rejects_missing_secret_and_bad_signature() -> None:
    body = b'{"event":"file_update","timestamp":1}'
    with pytest.raises(HTTPException) as missing:
        _verify_secret(body, None, None, require_secret=True)
    assert missing.value.status_code == 503

    with pytest.raises(HTTPException) as no_sig:
        _verify_secret(body, None, "super-secret", require_secret=True)
    assert no_sig.value.status_code == 401

    with pytest.raises(HTTPException) as bad:
        _verify_secret(body, "deadbeef", "super-secret", require_secret=True)
    assert bad.value.status_code == 401

    good = hmac.new(b"super-secret", body, hashlib.sha256).hexdigest()
    _verify_secret(body, f"sha256={good}", "super-secret", require_secret=True)


def test_production_rejects_placeholder_secrets() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            APP_ENV="production",
            AUTH_COOKIE_SECURE=True,
            JWT_SECRET_KEY="change-me",
            NEXTCLOUD_BRIDGE_SHARED_SECRET="a-sufficiently-long-bridge-secret",
            NEXTCLOUD_WEBHOOK_SECRET="webhook-secret-value",
            FIRST_SUPERUSER_PASSWORD="NotDefaultPass1!",
        )


def test_test_env_allows_placeholder_secrets() -> None:
    cfg = Settings(
        APP_ENV="test",
        JWT_SECRET_KEY="change-me",
        NEXTCLOUD_BRIDGE_SHARED_SECRET="change-me",
        NEXTCLOUD_WEBHOOK_SECRET=None,
        FIRST_SUPERUSER_PASSWORD="ChangeMe123!",
    )
    assert cfg.APP_ENV == "test"


@pytest.mark.asyncio
async def test_deleted_document_neighbors_are_not_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object.__new__(ChatService)
    doc_id = uuid4()
    chunk_id = uuid4()
    auth = AuthContext(
        user_id=str(uuid4()),
        auth_provider="local",
        username="bob",
        is_superuser=False,
    )

    class FakeRepo:
        def __init__(self, session: object) -> None:
            self.session = session

        async def list_authorized_by_document(self, **kwargs: object) -> list[object]:
            # Simulate ACL/deleted filter: nothing visible.
            assert kwargs["auth"] is auth
            return []

    monkeypatch.setattr(
        "backend.services.chat_service.DocumentChunkRepository",
        FakeRepo,
    )
    service.session = object()
    sources = await service._build_follow_up_neighbor_sources(
        question="what comes after that?",
        preferred_chunk_refs=[(doc_id, chunk_id)],
        auth=auth,
        document_ids_scope=None,
    )
    assert sources == []


@pytest.mark.asyncio
async def test_hard_scope_blocks_out_of_scope_neighbors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object.__new__(ChatService)
    in_scope = uuid4()
    out_scope = uuid4()
    auth = AuthContext(
        user_id=str(uuid4()),
        auth_provider="local",
        username="bob",
        is_superuser=False,
    )
    calls: list[object] = []

    class FakeRepo:
        def __init__(self, session: object) -> None:
            self.session = session

        async def list_authorized_by_document(self, **kwargs: object) -> list[object]:
            calls.append(kwargs)
            return []

    monkeypatch.setattr(
        "backend.services.chat_service.DocumentChunkRepository",
        FakeRepo,
    )
    service.session = object()
    await service._build_follow_up_neighbor_sources(
        question="what comes next after that section?",
        preferred_chunk_refs=[(out_scope, uuid4()), (in_scope, uuid4())],
        auth=auth,
        document_ids_scope=[in_scope],
    )
    assert len(calls) == 2
    assert calls[0]["document_ids_scope"] == [in_scope]
    # Repo itself enforces scope; out-of-scope docs return [].
    assert calls[0]["document_id"] == out_scope
    assert calls[1]["document_id"] == in_scope
