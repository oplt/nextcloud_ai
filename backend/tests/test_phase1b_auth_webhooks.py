"""Phase 1B: ACL neighbors, public-link grants, webhook auth."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.connectors.nextcloud.identity import (
    namespace_local_user,
    namespace_nc_group,
    namespace_nc_user,
    share_has_read,
)
from backend.connectors.nextcloud.permissions import NextcloudPermissionService
from backend.connectors.nextcloud.schemas import ShareGrant
from backend.connectors.nextcloud.config import NextcloudBridgeSettings
from backend.connectors.nextcloud.webhooks import _verify_secret
from backend.connectors.nextcloud.webhooks import _event_id, _verify_freshness
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
    no_expiry = ShareGrant.model_validate(
        {
            "id": "4a",
            "share_type": 0,
            "permissions": 1,
            "path": "/b",
            "share_with": "bob",
            "expiration": False,
        }
    )
    assert no_expiry.expiration is False
    malformed = ShareGrant(
        share_id="4b",
        share_type=0,
        permissions=1,
        path="/b",
        share_with="alice",
        expiration="not-a-date",
    )
    assert (
        service._apply_share(
            malformed,
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
    assert (
        namespace_nc_group("https://nc.example/nextcloud", "finance") in allowed_groups
    )
    assert 6 in unresolved
    assert "bob@other" not in allowed_groups


def test_ancestor_paths_deepest_first() -> None:
    assert NextcloudPermissionService.ancestor_paths("/Docs/a/b.txt") == [
        "/Docs/a/b.txt",
        "/Docs/a",
        "/Docs",
        "/",
    ]
    assert NextcloudPermissionService.ancestor_paths("/") == ["/"]
    assert NextcloudPermissionService.ancestor_paths("Docs/x") == [
        "/Docs/x",
        "/Docs",
        "/",
    ]


@pytest.mark.asyncio
async def test_inherited_parent_folder_user_share_applies_to_nested_file() -> None:
    parent_share = ShareGrant(
        share_id="parent-1",
        share_type=0,
        permissions=1,
        path="/Docs",
        share_with="alice",
        uid_owner="owner",
    )
    file_share = ShareGrant(
        share_id="file-1",
        share_type=1,
        permissions=1,
        path="/Docs/report.txt",
        share_with="finance",
        uid_owner="owner",
    )
    calls: list[str] = []

    class _Client:
        async def get_shares(self, remote_path: str):
            calls.append(remote_path)
            if remote_path == "/Docs/report.txt":
                return [file_share]
            if remote_path == "/Docs":
                return [parent_share]
            return []

        config = SimpleNamespace(base_url="https://nc.example")

    service = NextcloudPermissionService(client=_Client())  # type: ignore[arg-type]
    acl = await service.build_acl_for_path(
        "/Docs/report.txt",
        owner_user_id="owner",
        instance_base_url="https://nc.example",
    )
    assert calls[0] == "/Docs/report.txt"
    assert "/Docs" in calls
    assert namespace_nc_user("https://nc.example", "alice") in acl.allowed_user_ids
    assert namespace_nc_group("https://nc.example", "finance") in acl.allowed_group_ids
    assert acl.public_link_enabled is False


def test_circles_talk_email_share_types_fail_closed() -> None:
    service = NextcloudPermissionService(client=SimpleNamespace())  # type: ignore[arg-type]
    for share_type in (4, 7, 10):
        allowed_users: set[str] = set()
        allowed_groups: set[str] = set()
        unresolved: set[int] = set()
        result = service._apply_share(
            ShareGrant(
                share_id=str(share_type),
                share_type=share_type,
                permissions=31,
                path="/x",
                share_with="someone",
            ),
            allowed_users,
            allowed_groups,
            unresolved,
            instance_base_url="https://nc.example",
            now=datetime.now(timezone.utc),
        )
        assert result == "unsupported"
        assert share_type in unresolved
        assert allowed_users == set()
        assert allowed_groups == set()


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

    timestamp = "1700000000"
    timestamped = hmac.new(
        b"super-secret", timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    _verify_secret(
        body,
        f"sha256={timestamped}",
        "super-secret",
        require_secret=True,
        signed_timestamp=timestamp,
    )
    with pytest.raises(HTTPException):
        _verify_secret(
            body,
            f"sha256={good}",
            "super-secret",
            require_secret=True,
            signed_timestamp=timestamp,
        )


def test_webhook_timestamp_mismatch_and_replay_key_rotation_rejected() -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    with pytest.raises(HTTPException, match="timestamps do not match"):
        _verify_freshness(
            header_timestamp=str(now),
            payload_timestamp=now - 1,
        )
    payload = {"event": "file_update", "path": "/x"}
    assert _event_id(payload, now) == _event_id(payload, now + 30)


@pytest.mark.asyncio
async def test_webhook_route_rejects_replayed_signed_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import SecretStr
    from backend.connectors.nextcloud import webhooks
    from backend.connectors.nextcloud.replay_store import InMemoryReplayStore

    now = int(datetime.now(timezone.utc).timestamp())
    raw_body = json.dumps(
        {"event": "file_update", "path": "/docs/a.txt", "timestamp": now},
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(b"super-secret-value", raw_body, hashlib.sha256).hexdigest()
    bridge = NextcloudBridgeSettings(
        bridge_shared_secret=SecretStr("a-sufficiently-long-bridge-secret"),
        bridge_issuer="nextcloud-bridge",
        bridge_audience="fastapi-nextcloud",
        bridge_ttl_seconds=60,
        allowed_clock_skew_seconds=15,
        webhook_secret=SecretStr("super-secret-value"),
    )
    replay = InMemoryReplayStore(namespace="phase1-webhook-test")

    class FakeDispatch:
        def to_dict(self) -> dict[str, object]:
            return {"accepted": True, "scheduled": False, "action": "ignored"}

    class FakeAutomation:
        def __init__(self, _session: object) -> None:
            pass

        async def dispatch_webhook_event(self, _event: object) -> FakeDispatch:
            return FakeDispatch()

    def request() -> Request:
        sent = False

        async def receive() -> dict[str, object]:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": raw_body, "more_body": False}

        return Request({"type": "http", "method": "POST", "path": "/"}, receive)

    monkeypatch.setattr(webhooks, "_webhook_replay_store", lambda _settings: replay)
    monkeypatch.setattr(webhooks, "NextcloudAutomationService", FakeAutomation)
    first = await webhooks.receive_nextcloud_webhook(
        request(),
        object(),  # type: ignore[arg-type]
        bridge,
        x_webhook_signature=f"sha256={signature}",
    )
    assert first["accepted"] is True

    with pytest.raises(HTTPException) as replayed:
        await webhooks.receive_nextcloud_webhook(
            request(),
            object(),  # type: ignore[arg-type]
            bridge,
            x_webhook_signature=f"sha256={signature}",
        )
    assert replayed.value.status_code == 409


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

    with pytest.raises(ValueError, match="NEXTCLOUD_WEBHOOK_SECRET"):
        Settings(
            APP_ENV="production",
            AUTH_COOKIE_SECURE=True,
            JWT_SECRET_KEY="a-sufficiently-long-jwt-secret",
            NEXTCLOUD_BRIDGE_SHARED_SECRET="a-sufficiently-long-bridge-secret",
            NEXTCLOUD_WEBHOOK_SECRET="webhook-secret-value",
            FIRST_SUPERUSER_PASSWORD="NotDefaultPass1!",
        )

    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            APP_ENV="production",
            AUTH_COOKIE_SECURE=True,
            JWT_SECRET_KEY="replace-with-openssl-rand-base64-64",
            NEXTCLOUD_BRIDGE_SHARED_SECRET="a-sufficiently-long-bridge-secret",
            NEXTCLOUD_WEBHOOK_SECRET="a-sufficiently-long-webhook-secret",
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


def test_bridge_token_replay_store_falls_back_to_application_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import SecretStr
    from backend.api.v1 import nextcloud_auth

    bridge = NextcloudBridgeSettings(
        bridge_shared_secret=SecretStr("a-sufficiently-long-bridge-secret"),
        bridge_issuer="nextcloud-bridge",
        bridge_audience="fastapi-nextcloud",
        bridge_ttl_seconds=60,
        allowed_clock_skew_seconds=15,
        bridge_redis_url=None,
    )
    seen: list[str] = []

    class FakeReplayStore:
        def __init__(self, *, redis_url: str) -> None:
            seen.append(redis_url)

    nextcloud_auth.get_bridge_codec.cache_clear()
    monkeypatch.setattr(nextcloud_auth, "get_nextcloud_settings", lambda: bridge)
    monkeypatch.setattr(nextcloud_auth, "RedisReplayStore", FakeReplayStore)
    monkeypatch.setattr(
        nextcloud_auth,
        "settings",
        SimpleNamespace(REDIS_URL="redis://redis:6379/0"),
    )
    try:
        codec = nextcloud_auth.get_bridge_codec()
        assert codec.replay_store is not None
        assert seen == ["redis://redis:6379/0"]
    finally:
        nextcloud_auth.get_bridge_codec.cache_clear()


@pytest.mark.asyncio
async def test_bridge_token_is_one_time_use() -> None:
    from pydantic import SecretStr
    from backend.connectors.nextcloud.auth import BridgeTokenCodec
    from backend.connectors.nextcloud.exceptions import BridgeTokenError
    from backend.connectors.nextcloud.replay_store import InMemoryReplayStore

    bridge = NextcloudBridgeSettings(
        bridge_shared_secret=SecretStr("a-sufficiently-long-bridge-secret"),
        bridge_issuer="nextcloud-bridge",
        bridge_audience="fastapi-nextcloud",
        bridge_ttl_seconds=60,
        allowed_clock_skew_seconds=15,
    )
    codec = BridgeTokenCodec(
        settings=bridge,
        replay_store=InMemoryReplayStore(namespace="phase1-bridge-token"),
    )
    token = codec.issue_token(
        sub="alice",
        username="alice",
        nc_base_url="https://nc.example",
    )
    claims = await codec.verify_and_consume(token)
    assert claims.sub == "alice"
    with pytest.raises(BridgeTokenError, match="Replay detected"):
        await codec.verify_and_consume(token)


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

        async def list_grouped(self, **kwargs: object) -> dict[str, list[object]]:
            # Simulate ACL/deleted filter: nothing visible.
            assert kwargs["auth"] is auth
            return {str(doc_id): []}

    monkeypatch.setattr(
        "backend.services.chat_service.AuthorizedChunkExpansionRepository",
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

        async def list_grouped(self, **kwargs: object) -> dict[str, list[object]]:
            calls.append(kwargs)
            return {str(in_scope): []}

    monkeypatch.setattr(
        "backend.services.chat_service.AuthorizedChunkExpansionRepository",
        FakeRepo,
    )
    service.session = object()
    await service._build_follow_up_neighbor_sources(
        question="what comes next after that section?",
        preferred_chunk_refs=[(out_scope, uuid4()), (in_scope, uuid4())],
        auth=auth,
        document_ids_scope=[in_scope],
    )
    assert len(calls) == 1
    assert calls[0]["document_ids_scope"] == [in_scope]
    # The batched repository enforces scope inside the authorized SQL query.
    assert calls[0]["document_ids"] == [out_scope, in_scope]


@pytest.mark.asyncio
async def test_delivery_recheck_drops_revoked_and_out_of_scope_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object.__new__(ChatService)
    service.session = object()
    allowed_document = uuid4()
    revoked_document = uuid4()
    auth = AuthContext(
        user_id=str(uuid4()),
        auth_provider="local",
        username="alice",
        is_superuser=False,
    )

    def source(document_id):  # noqa: ANN001
        from backend.schemas.chat_schema import ChatSource

        return ChatSource(
            chunk_id=uuid4(),
            document_id=document_id,
            file_name="source.txt",
            file_path="/source.txt",
            snippet="authorized evidence",
            content="authorized evidence",
            distance=0.1,
            score=0.9,
        )

    class FakeRepo:
        def __init__(self, session: object) -> None:
            self.session = session

        async def filter_authorized_document_ids(self, **kwargs: object) -> set[str]:
            assert kwargs["auth"] is auth
            assert kwargs["document_ids_scope"] == [allowed_document]
            return {str(allowed_document)}

    monkeypatch.setattr(
        "backend.services.chat_service.DocumentChunkRepository",
        FakeRepo,
    )
    filtered = await service._recheck_sources_authorized(
        sources=[source(allowed_document), source(revoked_document)],
        auth=auth,
        document_ids_scope=[allowed_document],
    )
    assert [item.document_id for item in filtered] == [allowed_document]
