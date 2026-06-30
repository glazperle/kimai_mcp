"""Tool execution errors must be reported with ``isError=True`` (issue #18).

Both transports caught exceptions into a plain ``TextContent`` and returned a
``CallToolResult`` with ``isError`` unset, so a programmatic MCP client could
not distinguish a failure from success. The handlers now return a
``CallToolResult(isError=True)`` (built by ``error_result``) on the exception
paths, while preserving the rich ``format_api_error`` message.

The MCP SDK passes a handler-supplied ``CallToolResult`` through unchanged
(``mcp/server/lowlevel/server.py``), so asserting on the handler return value
is equivalent to asserting on what the client receives.
"""

import pytest
from unittest.mock import AsyncMock
from mcp.types import CallToolResult

from kimai_mcp.client import KimaiAPIError, KimaiClient
from kimai_mcp.server import KimaiMCPServer
from kimai_mcp.streamable_http_server import UserMCPSession
from kimai_mcp.user_config import UserConfig
from kimai_mcp.tools.errors import ToolError
from kimai_mcp.tools import entity_manager, rate_manager


def _assert_error(result, *expected_substrings):
    assert isinstance(
        result, CallToolResult
    ), f"Expected CallToolResult, got {type(result)}"
    assert result.isError is True, "Tool execution error must set isError=True"
    text = "\n".join(c.text for c in result.content)
    for sub in expected_substrings:
        assert sub in text, f"Expected {sub!r} in error text:\n{text}"


def _raise(exc):
    async def _dispatch(client, name, arguments):
        raise exc

    return _dispatch


# ---------------------------------------------------------------------------
# Local stdio server (server.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def local_server():
    # No network happens on construction or in _ensure_client (KimaiClient
    # only connects when a request is actually made, which we never reach).
    return KimaiMCPServer(base_url="http://example.invalid", api_token="t")


@pytest.mark.asyncio
async def test_local_kimai_api_error_sets_iserror(local_server, monkeypatch):
    err = KimaiAPIError("nope", status_code=403, details={"field": "bad"})
    monkeypatch.setattr("kimai_mcp.server.dispatch_tool", _raise(err))

    result = await local_server._call_tool(
        "entity", {"type": "project", "action": "list"}
    )

    _assert_error(result, "Kimai API Error", "Status: 403", "lacks permission")


@pytest.mark.asyncio
async def test_local_generic_exception_sets_iserror(local_server, monkeypatch):
    monkeypatch.setattr("kimai_mcp.server.dispatch_tool", _raise(RuntimeError("boom")))

    result = await local_server._call_tool(
        "entity", {"type": "project", "action": "list"}
    )

    _assert_error(result, "Error: boom")


# ---------------------------------------------------------------------------
# Streamable HTTP server (streamable_http_server.py)
# ---------------------------------------------------------------------------


def _make_session() -> UserMCPSession:
    config = UserConfig(kimai_url="http://example.invalid", kimai_token="t")
    return UserMCPSession("alice", config)


@pytest.mark.asyncio
async def test_streamable_client_not_initialized_sets_iserror():
    session = _make_session()
    # kimai_client is None until initialize() is called.
    result = await session._call_tool("entity", {"type": "project", "action": "list"})

    _assert_error(result, "Kimai client not initialized")


@pytest.mark.asyncio
async def test_streamable_kimai_api_error_sets_iserror(monkeypatch):
    session = _make_session()
    session.kimai_client = object()  # sentinel so the not-initialized guard is skipped
    err = KimaiAPIError("nope", status_code=403, details={"field": "bad"})
    monkeypatch.setattr("kimai_mcp.streamable_http_server.dispatch_tool", _raise(err))

    result = await session._call_tool("entity", {"type": "project", "action": "list"})

    _assert_error(result, "Kimai API Error", "Status: 403", "lacks permission")


@pytest.mark.asyncio
async def test_streamable_generic_exception_sets_iserror(monkeypatch):
    session = _make_session()
    session.kimai_client = object()  # sentinel so the not-initialized guard is skipped
    monkeypatch.setattr(
        "kimai_mcp.streamable_http_server.dispatch_tool", _raise(RuntimeError("boom"))
    )

    result = await session._call_tool("entity", {"type": "project", "action": "list"})

    _assert_error(result, "Error: boom")


# ---------------------------------------------------------------------------
# ToolError (in-handler validation / unsupported operations) -> isError=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_tool_error_sets_iserror(local_server, monkeypatch):
    monkeypatch.setattr(
        "kimai_mcp.server.dispatch_tool", _raise(ToolError("Error: bad input"))
    )

    result = await local_server._call_tool(
        "entity", {"type": "project", "action": "list"}
    )

    _assert_error(result, "Error: bad input")


@pytest.mark.asyncio
async def test_streamable_tool_error_sets_iserror(monkeypatch):
    session = _make_session()
    session.kimai_client = object()  # sentinel so the not-initialized guard is skipped
    monkeypatch.setattr(
        "kimai_mcp.streamable_http_server.dispatch_tool",
        _raise(ToolError("Error: bad input")),
    )

    result = await session._call_tool("entity", {"type": "project", "action": "list"})

    _assert_error(result, "Error: bad input")


# ---------------------------------------------------------------------------
# Representative handlers raise ToolError (rather than returning "Error:" text)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_unknown_action_raises_tool_error():
    client = AsyncMock(spec=KimaiClient)
    with pytest.raises(ToolError, match="Unknown action"):
        await entity_manager.handle_entity(client, type="project", action="frobnicate")


@pytest.mark.asyncio
async def test_entity_unsupported_operation_raises_tool_error():
    client = AsyncMock(spec=KimaiClient)
    with pytest.raises(ToolError, match="Invoice creation is not supported"):
        await entity_manager.handle_entity(
            client, type="invoice", action="create", data={"name": "x"}
        )


@pytest.mark.asyncio
async def test_rate_missing_entity_id_raises_tool_error():
    client = AsyncMock(spec=KimaiClient)
    with pytest.raises(ToolError, match="'entity_id' parameter is required"):
        await rate_manager.handle_rate(client, entity="project", action="list")
