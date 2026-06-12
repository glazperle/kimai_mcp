"""Tests for security fixes: trusted-proxy IP extraction and users.json validation."""

import json

import pytest
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from kimai_mcp.security import (
    RateLimitConfig,
    RateLimitMiddleware,
    get_client_ip,
)
from kimai_mcp.user_config import UsersConfig


def make_scope(client_ip="10.0.0.1", headers=None):
    raw_headers = [
        (name.lower().encode(), value.encode()) for name, value in (headers or {}).items()
    ]
    return {
        "type": "http",
        "client": (client_ip, 12345),
        "headers": raw_headers,
    }


# ---------------------------------------------------------------------------
# get_client_ip: X-Forwarded-For / X-Real-IP handling
# ---------------------------------------------------------------------------


def test_xff_ignored_without_trusted_proxy():
    scope = make_scope("10.0.0.1", {"X-Forwarded-For": "6.6.6.6"})
    assert get_client_ip(scope) == "10.0.0.1"
    assert get_client_ip(scope, trusted_proxies=[]) == "10.0.0.1"


def test_x_real_ip_ignored_without_trusted_proxy():
    scope = make_scope("10.0.0.1", {"X-Real-IP": "6.6.6.6"})
    assert get_client_ip(scope) == "10.0.0.1"


def test_xff_honored_from_trusted_proxy():
    # The trusted proxy appends the real peer to the RIGHT; the leftmost entry is
    # client-supplied and spoofable, so the last hop is the trustworthy one.
    scope = make_scope("10.0.0.1", {"X-Forwarded-For": "203.0.113.7, 198.51.100.9"})
    assert get_client_ip(scope, trusted_proxies=["10.0.0.1"]) == "198.51.100.9"


def test_xff_spoofed_leftmost_is_not_trusted():
    # Attacker prepends a fake IP; the proxy appends the real peer. We must not
    # key rate limiting on the attacker-chosen leftmost value.
    scope = make_scope("10.0.0.1", {"X-Forwarded-For": "1.2.3.4, 198.51.100.9"})
    assert get_client_ip(scope, trusted_proxies=["10.0.0.1"]) == "198.51.100.9"


def test_x_real_ip_honored_from_trusted_proxy():
    scope = make_scope("10.0.0.1", {"X-Real-IP": "203.0.113.7"})
    assert get_client_ip(scope, trusted_proxies=["10.0.0.1"]) == "203.0.113.7"


def test_xff_ignored_from_untrusted_peer_even_with_proxies_configured():
    scope = make_scope("192.168.1.50", {"X-Forwarded-For": "6.6.6.6"})
    assert get_client_ip(scope, trusted_proxies=["10.0.0.1"]) == "192.168.1.50"


def test_direct_client_without_headers():
    scope = make_scope("10.0.0.1")
    assert get_client_ip(scope, trusted_proxies=["10.0.0.1"]) == "10.0.0.1"


# ---------------------------------------------------------------------------
# RateLimitMiddleware integration: spoofed XFF cannot evade rate limiting
# ---------------------------------------------------------------------------


async def _ok_app(scope, receive, send):
    response = JSONResponse({"ok": True})
    await response(scope, receive, send)


def test_rate_limit_not_evadable_via_spoofed_xff():
    """Without trusted proxies, varying XFF headers share one bucket per real IP."""
    config = RateLimitConfig(requests_per_minute=60, burst_limit=1, enabled=True)
    app = RateLimitMiddleware(_ok_app, config)  # no trusted proxies
    client = TestClient(app)

    first = client.get("/", headers={"X-Forwarded-For": "1.1.1.1"})
    second = client.get("/", headers={"X-Forwarded-For": "2.2.2.2"})
    assert first.status_code == 200
    assert second.status_code == 429  # spoofed XFF did not reset the bucket


def test_rate_limit_uses_xff_from_trusted_proxy():
    """With the direct peer trusted, distinct forwarded IPs get distinct buckets."""
    config = RateLimitConfig(requests_per_minute=60, burst_limit=1, enabled=True)
    # starlette's TestClient sets the peer address to "testclient"
    app = RateLimitMiddleware(_ok_app, config, trusted_proxies=["testclient"])
    client = TestClient(app)

    first = client.get("/", headers={"X-Forwarded-For": "1.1.1.1"})
    second = client.get("/", headers={"X-Forwarded-For": "2.2.2.2"})
    assert first.status_code == 200
    assert second.status_code == 200


# ---------------------------------------------------------------------------
# users.json: slug validation and auth_secret parsing
# ---------------------------------------------------------------------------


def _write_users_file(tmp_path, data):
    path = tmp_path / "users.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_invalid_slug_in_users_file_is_skipped(tmp_path):
    # An invalid slug must not abort the whole load (that would take the server
    # down for every valid user on upgrade); it is skipped with a warning.
    path = _write_users_file(
        tmp_path,
        {
            "bad slug!": {"kimai_url": "https://kimai.example.com", "kimai_token": "t"},
            "validSlug123": {"kimai_url": "https://kimai.example.com", "kimai_token": "t"},
        },
    )
    config = UsersConfig.from_file(path)
    assert "bad slug!" not in config.users
    assert "validSlug123" in config.users


def test_only_invalid_slugs_in_users_file_raises(tmp_path):
    # If nothing valid remains, loading still fails clearly.
    path = _write_users_file(
        tmp_path,
        {"bad slug!": {"kimai_url": "https://kimai.example.com", "kimai_token": "t"}},
    )
    with pytest.raises(ValueError, match="No users configured"):
        UsersConfig.from_file(path)


def test_invalid_slug_via_model_raises():
    with pytest.raises(ValueError, match="Invalid user slug"):
        UsersConfig(
            users={
                "slug/with/slashes": {
                    "kimai_url": "https://kimai.example.com",
                    "kimai_token": "t",
                }
            }
        )


def test_auth_secret_is_parsed_from_users_file(tmp_path):
    path = _write_users_file(
        tmp_path,
        {
            "validSlug123": {
                "kimai_url": "https://kimai.example.com",
                "kimai_token": "t",
                "auth_secret": "my-oauth-secret",
            }
        },
    )
    config = UsersConfig.from_file(path)
    assert config.users["validSlug123"].auth_secret == "my-oauth-secret"


def test_auth_secret_defaults_to_none(tmp_path):
    path = _write_users_file(
        tmp_path,
        {"validSlug123": {"kimai_url": "https://kimai.example.com", "kimai_token": "t"}},
    )
    config = UsersConfig.from_file(path)
    assert config.users["validSlug123"].auth_secret is None


def test_auth_secret_from_env_overrides_file(tmp_path, monkeypatch):
    path = _write_users_file(
        tmp_path,
        {
            "max-mustermann": {
                "kimai_url": "https://kimai.example.com",
                "kimai_token": "t",
                "auth_secret": "file-secret",
            }
        },
    )
    monkeypatch.setenv("KIMAI_USER_MAX_MUSTERMANN_AUTH_SECRET", "env-secret")
    config = UsersConfig.from_file(path)
    assert config.users["max-mustermann"].auth_secret == "env-secret"


def test_legacy_kimai_user_id_field_is_ignored(tmp_path):
    """Old users.json files with the removed kimai_user_id field still load."""
    path = _write_users_file(
        tmp_path,
        {
            "validSlug123": {
                "kimai_url": "https://kimai.example.com",
                "kimai_token": "t",
                "kimai_user_id": "1",
            }
        },
    )
    config = UsersConfig.from_file(path)
    user = config.users["validSlug123"]
    assert not hasattr(user, "kimai_user_id")


def test_comment_keys_in_users_file_are_skipped(tmp_path):
    path = _write_users_file(
        tmp_path,
        {
            "_SECURITY_WARNING": "use random slugs",
            "validSlug123": {"kimai_url": "https://kimai.example.com", "kimai_token": "t"},
        },
    )
    config = UsersConfig.from_file(path)
    assert list(config.users) == ["validSlug123"]


def test_auth_secret_from_env_vars_config(monkeypatch):
    monkeypatch.setenv("KIMAI_USER_TESTUSER_URL", "https://kimai.example.com")
    monkeypatch.setenv("KIMAI_USER_TESTUSER_TOKEN", "tok")
    monkeypatch.setenv("KIMAI_USER_TESTUSER_AUTH_SECRET", "env-oauth-secret")
    config = UsersConfig.from_env()
    assert config.users["testuser"].auth_secret == "env-oauth-secret"
