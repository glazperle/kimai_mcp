"""Tests for the personal API token endpoints of the ApiTokenBundle plugin.

The token value is the whole point of ``create_api_token``: Kimai returns it
exactly once, so a parsing slip here does not degrade gracefully, it loses a
credential that cannot be fetched again.
"""

import json

import pytest

from kimai_mcp.client import KimaiAPIError, KimaiClient

BASE_URL = "https://kimai.example.com"
TOKEN_URL = f"{BASE_URL}/api/users/7/api-token"


def make_client() -> KimaiClient:
    return KimaiClient(BASE_URL, "admin-token")


@pytest.mark.asyncio
async def test_create_api_token_returns_the_token(httpx_mock):
    httpx_mock.add_response(
        url=TOKEN_URL,
        method="POST",
        status_code=201,
        json={
            "id": 42,
            "name": "Kimai MCP (auto)",
            "token": "abc123",
            "lastUsage": None,
            "expiresAt": None,
        },
    )

    async with make_client() as client:
        created = await client.create_api_token(user_id=7, name="Kimai MCP (auto)")

    assert created.token == "abc123"
    assert created.id == 42
    assert created.name == "Kimai MCP (auto)"
    assert created.expires_at is None


@pytest.mark.asyncio
async def test_create_api_token_sends_the_expected_payload(httpx_mock):
    httpx_mock.add_response(
        url=TOKEN_URL, method="POST", status_code=201, json={"id": 1, "token": "t"}
    )

    async with make_client() as client:
        await client.create_api_token(user_id=7, name="ci", expires_at="2027-01-01")

    payload = json.loads(httpx_mock.get_requests()[0].content)
    assert payload == {"name": "ci", "replaceExisting": True, "expiresAt": "2027-01-01"}


@pytest.mark.asyncio
async def test_create_api_token_omits_an_unset_expiry(httpx_mock):
    httpx_mock.add_response(
        url=TOKEN_URL, method="POST", status_code=201, json={"id": 1, "token": "t"}
    )

    async with make_client() as client:
        await client.create_api_token(user_id=7, name="ci", replace_existing=False)

    payload = json.loads(httpx_mock.get_requests()[0].content)
    assert payload == {"name": "ci", "replaceExisting": False}


@pytest.mark.asyncio
async def test_create_api_token_without_the_plugin_raises_404(httpx_mock):
    httpx_mock.add_response(url=TOKEN_URL, method="POST", status_code=404, json={})

    async with make_client() as client:
        with pytest.raises(KimaiAPIError) as excinfo:
            await client.create_api_token(user_id=7, name="ci")

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_get_api_tokens_returns_metadata_only(httpx_mock):
    httpx_mock.add_response(
        url=TOKEN_URL,
        method="GET",
        json=[
            {"id": 1, "name": "laptop", "lastUsage": "2026-08-01T10:00:00+0200", "expiresAt": None},
            {"id": 2, "name": "Kimai MCP (auto)", "lastUsage": None, "expiresAt": None},
        ],
    )

    async with make_client() as client:
        tokens = await client.get_api_tokens(user_id=7)

    assert [t.name for t in tokens] == ["laptop", "Kimai MCP (auto)"]
    assert tokens[0].last_usage == "2026-08-01T10:00:00+0200"
    # The listing endpoint must never carry the token value itself.
    assert not any(hasattr(t, "token") for t in tokens)
