"""Tests for the embedded OAuth 2.1 authorization server (streamable HTTP server).

All tests run against the Starlette ASGI app in-process (no real network
server); Kimai API calls are mocked out.
"""

import asyncio
import base64
import contextlib
import hashlib
import secrets
import time
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.testclient import TestClient

from kimai_mcp.streamable_http_server import StreamableHTTPMCPServer
from kimai_mcp.user_config import UsersConfig, UserConfig

PUBLIC_URL = "http://localhost:8000"
REDIRECT_URI = "http://localhost:9876/callback"

USER_SLUG = "x7Kp2mQ9wL4rT6vN"
AUTH_SECRET = "super-secret-oauth-login-secret"
NO_OAUTH_SLUG = "noOauthUserSlug16"

INIT_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "1.0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


class FakeVersion:
    version = "2.40.0"


class FakeKimaiClient:
    """Stand-in for KimaiClient - no network access."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False

    async def get_version(self):
        return FakeVersion()

    async def close(self):
        self.closed = True


@pytest.fixture
def users_config() -> UsersConfig:
    return UsersConfig(
        users={
            USER_SLUG: UserConfig(
                kimai_url="https://kimai.example.com",
                kimai_token="token-1",
                auth_secret=AUTH_SECRET,
            ),
            NO_OAUTH_SLUG: UserConfig(
                kimai_url="https://kimai.example.com",
                kimai_token="token-2",
            ),
        }
    )


@pytest.fixture
def make_client(users_config, monkeypatch):
    """Factory creating a TestClient (lifespan running) for a server instance."""
    monkeypatch.setattr(
        "kimai_mcp.streamable_http_server.KimaiClient", FakeKimaiClient
    )
    stack = contextlib.ExitStack()

    def _make(**server_kwargs) -> TestClient:
        server = StreamableHTTPMCPServer(
            users_config=server_kwargs.pop("users_config", users_config),
            rate_limit_rpm=server_kwargs.pop("rate_limit_rpm", 0),
            public_url=server_kwargs.pop("public_url", PUBLIC_URL),
            **server_kwargs,
        )
        return stack.enter_context(TestClient(server.create_app(), base_url=PUBLIC_URL))

    yield _make
    stack.close()


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


def register_client(http: TestClient) -> dict:
    resp = http.post(
        "/register",
        json={
            "client_name": "Test Client",
            "redirect_uris": [REDIRECT_URI],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def start_authorization(http: TestClient, client_id: str, challenge: str, state: str = "st4te") -> str:
    """GET /authorize and return the login transaction id."""
    resp = http.get(
        "/authorize",
        params={
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text
    location = resp.headers["location"]
    assert location.startswith(f"{PUBLIC_URL}/oauth/login?txn=")
    return parse_qs(urlparse(location).query)["txn"][0]


def login_and_get_code(http: TestClient, txn: str, state: str = "st4te") -> str:
    """POST the login form and return the authorization code."""
    resp = http.post(
        "/oauth/login",
        data={"txn": txn, "username": USER_SLUG, "secret": AUTH_SECRET},
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text
    location = resp.headers["location"]
    assert location.startswith(REDIRECT_URI)
    query = parse_qs(urlparse(location).query)
    assert query["state"][0] == state
    return query["code"][0]


def obtain_tokens(http: TestClient) -> dict:
    """Run the complete PKCE authorization code flow and return the token response."""
    client_info = register_client(http)
    verifier, challenge = pkce_pair()
    txn = start_authorization(http, client_info["client_id"], challenge)
    code = login_and_get_code(http, txn)

    resp = http.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_info["client_id"],
            "code_verifier": verifier,
        },
    )
    assert resp.status_code == 200, resp.text
    tokens = resp.json()
    tokens["_client_id"] = client_info["client_id"]
    return tokens


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_authorization_server_metadata(make_client):
    http = make_client()
    resp = http.get("/.well-known/oauth-authorization-server")
    assert resp.status_code == 200
    data = resp.json()
    assert data["issuer"].rstrip("/") == PUBLIC_URL
    assert data["authorization_endpoint"] == f"{PUBLIC_URL}/authorize"
    assert data["token_endpoint"] == f"{PUBLIC_URL}/token"
    assert data["registration_endpoint"] == f"{PUBLIC_URL}/register"
    assert data["code_challenge_methods_supported"] == ["S256"]
    assert "authorization_code" in data["grant_types_supported"]


def test_protected_resource_metadata(make_client):
    http = make_client()
    resp = http.get("/.well-known/oauth-protected-resource/mcp")
    assert resp.status_code == 200
    data = resp.json()
    assert data["resource"].rstrip("/") == f"{PUBLIC_URL}/mcp"
    assert data["authorization_servers"][0].rstrip("/") == PUBLIC_URL


# ---------------------------------------------------------------------------
# Dynamic client registration
# ---------------------------------------------------------------------------


def test_dynamic_client_registration(make_client):
    http = make_client()
    client_info = register_client(http)
    assert client_info["client_id"]
    assert client_info["redirect_uris"] == [REDIRECT_URI]
    assert client_info["token_endpoint_auth_method"] == "none"


# ---------------------------------------------------------------------------
# Authorization code flow with PKCE
# ---------------------------------------------------------------------------


def test_full_pkce_flow_end_to_end(make_client):
    http = make_client()
    tokens = obtain_tokens(http)
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["token_type"].lower() == "bearer"
    assert tokens["expires_in"] == 3600


def test_login_page_renders_form(make_client):
    http = make_client()
    client_info = register_client(http)
    _, challenge = pkce_pair()
    txn = start_authorization(http, client_info["client_id"], challenge)

    resp = http.get(f"/oauth/login?txn={txn}")
    assert resp.status_code == 200
    assert "<form" in resp.text
    assert 'name="username"' in resp.text
    assert 'name="secret"' in resp.text


def test_login_with_wrong_secret_is_rejected(make_client):
    http = make_client()
    client_info = register_client(http)
    _, challenge = pkce_pair()
    txn = start_authorization(http, client_info["client_id"], challenge)

    resp = http.post(
        "/oauth/login",
        data={"txn": txn, "username": USER_SLUG, "secret": "wrong-secret"},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    assert "Invalid user slug or auth secret" in resp.text
    # No redirect with an authorization code was issued
    assert "location" not in resp.headers


def test_login_with_unknown_user_is_rejected(make_client):
    http = make_client()
    client_info = register_client(http)
    _, challenge = pkce_pair()
    txn = start_authorization(http, client_info["client_id"], challenge)

    resp = http.post(
        "/oauth/login",
        data={"txn": txn, "username": "doesNotExist12345", "secret": "whatever"},
        follow_redirects=False,
    )
    assert resp.status_code == 401


def test_login_user_without_auth_secret_is_rejected_without_disclosure(make_client):
    # A user that exists but has no auth_secret must get the SAME generic
    # rejection as an unknown slug, so the response cannot be used to enumerate
    # valid slugs (which are the credential for the legacy /mcp/{slug} endpoint).
    http = make_client()
    client_info = register_client(http)
    _, challenge = pkce_pair()
    txn = start_authorization(http, client_info["client_id"], challenge)

    resp = http.post(
        "/oauth/login",
        data={"txn": txn, "username": NO_OAUTH_SLUG, "secret": "anything"},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    assert "no auth_secret" not in resp.text
    assert NO_OAUTH_SLUG not in resp.text


def test_token_exchange_with_wrong_code_verifier_fails(make_client):
    http = make_client()
    client_info = register_client(http)
    _, challenge = pkce_pair()
    txn = start_authorization(http, client_info["client_id"], challenge)
    code = login_and_get_code(http, txn)

    resp = http.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_info["client_id"],
            "code_verifier": "completely-wrong-verifier-aaaaaaaaaaaaaaaaaaaa",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_grant"


def test_refresh_token_flow_rotates_tokens(make_client):
    http = make_client()
    tokens = obtain_tokens(http)

    resp = http.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": tokens["_client_id"],
        },
    )
    assert resp.status_code == 200, resp.text
    new_tokens = resp.json()
    assert new_tokens["access_token"] != tokens["access_token"]
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    # Old refresh token is no longer usable (rotation)
    resp = http.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": tokens["_client_id"],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_grant"

    # New access token works against /mcp
    resp = http.post(
        "/mcp",
        json=INIT_PAYLOAD,
        headers={**MCP_HEADERS, "Authorization": f"Bearer {new_tokens['access_token']}"},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Protected /mcp endpoint
# ---------------------------------------------------------------------------


def test_mcp_without_token_returns_401(make_client):
    http = make_client()
    resp = http.post("/mcp", json=INIT_PAYLOAD, headers=MCP_HEADERS)
    assert resp.status_code == 401
    assert "www-authenticate" in {k.lower() for k in resp.headers}


def test_mcp_with_invalid_token_returns_401(make_client):
    http = make_client()
    resp = http.post(
        "/mcp",
        json=INIT_PAYLOAD,
        headers={**MCP_HEADERS, "Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


def test_mcp_with_valid_token_reaches_user_session(make_client):
    http = make_client()
    tokens = obtain_tokens(http)
    resp = http.post(
        "/mcp",
        json=INIT_PAYLOAD,
        headers={**MCP_HEADERS, "Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200, resp.text
    # The streamable HTTP transport assigns a session on initialize
    assert "mcp-session-id" in {k.lower() for k in resp.headers}


@pytest.mark.asyncio
async def test_session_initialized_on_demand(users_config, monkeypatch):
    """A configured user whose startup init failed (no active session) is
    (re)initialized on demand instead of staying in a permanent 403/503 loop."""
    monkeypatch.setattr(
        "kimai_mcp.streamable_http_server.KimaiClient", FakeKimaiClient
    )
    server = StreamableHTTPMCPServer(
        users_config=users_config, public_url=PUBLIC_URL, rate_limit_rpm=0
    )
    # No sessions initialized yet (initialize_users was not run).
    assert USER_SLUG not in server.user_sessions

    session = await server._ensure_session(USER_SLUG)
    assert session is not None
    assert session.session_manager is not None
    assert server.user_sessions[USER_SLUG] is session

    # A second call returns the same (now active) session.
    assert await server._ensure_session(USER_SLUG) is session

    # An unknown slug is never initialized.
    assert await server._ensure_session("unconfigured-slug") is None


# ---------------------------------------------------------------------------
# Legacy slug routes
# ---------------------------------------------------------------------------


def test_legacy_slug_route_still_works(make_client):
    http = make_client()
    resp = http.post(f"/mcp/{USER_SLUG}", json=INIT_PAYLOAD, headers=MCP_HEADERS)
    assert resp.status_code == 200, resp.text


def test_legacy_unknown_slug_returns_404(make_client):
    http = make_client()
    resp = http.post("/mcp/unknownSlug123456", json=INIT_PAYLOAD, headers=MCP_HEADERS)
    assert resp.status_code == 404


def test_legacy_slugs_can_be_disabled(make_client):
    http = make_client(disable_legacy_slugs=True)
    resp = http.post(f"/mcp/{USER_SLUG}", json=INIT_PAYLOAD, headers=MCP_HEADERS)
    assert resp.status_code == 404
    # OAuth endpoint still answers (401 without a token)
    resp = http.post("/mcp", json=INIT_PAYLOAD, headers=MCP_HEADERS)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# OAuth client persistence (state file)
# ---------------------------------------------------------------------------


def test_client_registration_is_persisted_to_state_file(make_client, tmp_path):
    state_file = tmp_path / "oauth_clients.json"
    http = make_client(oauth_state_file=str(state_file))
    client_info = register_client(http)

    assert state_file.exists()
    # A new provider instance loads the persisted client
    from kimai_mcp.oauth import KimaiOAuthProvider
    from kimai_mcp.user_config import UsersConfig

    provider = KimaiOAuthProvider(
        users_config=UsersConfig(users={}), public_url=PUBLIC_URL, state_file=state_file
    )
    assert client_info["client_id"] in provider._clients


# ---------------------------------------------------------------------------
# Provider-level: refresh token resource/audience binding & client binding
# ---------------------------------------------------------------------------


def _make_provider(users_config, **kwargs):
    from kimai_mcp.oauth import KimaiOAuthProvider

    return KimaiOAuthProvider(
        users_config=users_config, public_url=PUBLIC_URL, **kwargs
    )


def _register_full_client(provider, client_id="client-A"):
    """Register a client directly on the provider and return it."""
    from mcp.shared.auth import OAuthClientInformationFull

    client = OAuthClientInformationFull(
        client_id=client_id,
        redirect_uris=[REDIRECT_URI],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )
    asyncio.run(provider.register_client(client))
    return client


def test_refresh_preserves_resource_binding(users_config):
    """After a refresh, the new access token keeps the original resource (RFC 8707)."""
    provider = _make_provider(users_config)
    client = _register_full_client(provider)
    resource = f"{PUBLIC_URL}/mcp"

    # Issue an initial token pair carrying a resource binding.
    initial = provider._issue_token_pair(
        client_id=client.client_id,
        scopes=["mcp"],
        subject=USER_SLUG,
        resource=resource,
    )
    first_access = provider._access_tokens[initial.access_token]
    assert first_access.resource == resource
    # The side mapping carries the resource for the refresh token.
    assert provider._refresh_token_resource[initial.refresh_token] == resource

    # First refresh.
    refresh_tok = provider._refresh_tokens[initial.refresh_token]
    refreshed = asyncio.run(
        provider.exchange_refresh_token(client, refresh_tok, ["mcp"])
    )
    new_access = provider._access_tokens[refreshed.access_token]
    assert new_access.resource == resource, "resource binding lost on first refresh"

    # Second refresh: binding must still be preserved (the original bug surfaced
    # only after the first rotation dropped the resource).
    refresh_tok2 = provider._refresh_tokens[refreshed.refresh_token]
    refreshed2 = asyncio.run(
        provider.exchange_refresh_token(client, refresh_tok2, ["mcp"])
    )
    new_access2 = provider._access_tokens[refreshed2.access_token]
    assert new_access2.resource == resource, "resource binding lost on second refresh"


def test_refresh_with_foreign_client_is_rejected(users_config):
    """A refresh token issued to client A must not be redeemable by client B."""
    from mcp.server.auth.provider import TokenError
    from mcp.shared.auth import OAuthClientInformationFull

    provider = _make_provider(users_config)
    client_a = _register_full_client(provider, client_id="client-A")

    issued = provider._issue_token_pair(
        client_id=client_a.client_id,
        scopes=["mcp"],
        subject=USER_SLUG,
        resource=None,
    )
    refresh_tok = provider._refresh_tokens[issued.refresh_token]

    # A different (attacker) client attempts to use the refresh token.
    client_b = OAuthClientInformationFull(
        client_id="client-B",
        redirect_uris=[REDIRECT_URI],
        token_endpoint_auth_method="none",
    )

    with pytest.raises(TokenError) as exc_info:
        asyncio.run(provider.exchange_refresh_token(client_b, refresh_tok, ["mcp"]))
    assert exc_info.value.error == "invalid_grant"

    # The original refresh token must remain valid for its real client.
    assert issued.refresh_token in provider._refresh_tokens
    refreshed = asyncio.run(
        provider.exchange_refresh_token(client_a, refresh_tok, ["mcp"])
    )
    assert refreshed.access_token


# ---------------------------------------------------------------------------
# Provider-level: client store cleanup (idle TTL)
# ---------------------------------------------------------------------------


def test_cleanup_removes_idle_client_but_keeps_active_one(users_config):
    from kimai_mcp.oauth import CLIENT_TTL_SECONDS

    provider = _make_provider(users_config)
    _register_full_client(provider, client_id="stale-client")
    _register_full_client(provider, client_id="fresh-client")

    now = time.time()
    # Simulate the stale client not being seen for longer than the TTL, while
    # the fresh client was just used. No real sleeping involved.
    provider._client_last_seen["stale-client"] = now - CLIENT_TTL_SECONDS - 100
    provider._client_last_seen["fresh-client"] = now

    removed = provider.cleanup_expired()

    assert removed >= 1
    assert "stale-client" not in provider._clients
    assert "stale-client" not in provider._client_last_seen
    assert "fresh-client" in provider._clients
    assert "fresh-client" in provider._client_last_seen


def test_cleanup_persists_client_store_after_pruning(users_config, tmp_path):
    from kimai_mcp.oauth import CLIENT_TTL_SECONDS

    state_file = tmp_path / "oauth_clients.json"
    provider = _make_provider(users_config, state_file=state_file)
    _register_full_client(provider, client_id="stale-client")
    _register_full_client(provider, client_id="fresh-client")

    provider._client_last_seen["stale-client"] = time.time() - CLIENT_TTL_SECONDS - 100

    provider.cleanup_expired()

    # The persisted state file must no longer contain the pruned client.
    fresh = _make_provider(users_config, state_file=state_file)
    assert "stale-client" not in fresh._clients
    assert "fresh-client" in fresh._clients


def test_get_client_renews_last_seen(users_config):
    from kimai_mcp.oauth import CLIENT_TTL_SECONDS

    provider = _make_provider(users_config)
    _register_full_client(provider, client_id="some-client")

    # Make it look idle, then touch it via get_client -> last-seen renewed.
    provider._client_last_seen["some-client"] = time.time() - CLIENT_TTL_SECONDS - 100
    found = asyncio.run(provider.get_client("some-client"))
    assert found is not None

    removed = provider.cleanup_expired()
    assert "some-client" in provider._clients
    assert removed == 0


def test_cleanup_removes_client_with_expired_secret(users_config):
    provider = _make_provider(users_config)
    client = _register_full_client(provider, client_id="secret-client")
    # Secret already expired in the past; last-seen is recent.
    client.client_secret_expires_at = int(time.time()) - 10
    provider._client_last_seen["secret-client"] = time.time()

    provider.cleanup_expired()
    assert "secret-client" not in provider._clients
