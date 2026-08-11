"""End-to-end tests through a real MCP client session.

Every other test calls the handlers directly, which is why issue #21 could ship:
MCP SDK 2.0.0 removed the ``list_tools()``/``call_tool()`` decorators, so
``KimaiMCPServer.__init__`` raised ``AttributeError`` before the handshake even
started, yet nothing in the suite performed a handshake.

These tests drive the server the way a client does - ``tools/list``,
``tools/call`` - over the SDK's in-memory transport, so a broken handler
registration, a wrong result type, or a lost ``is_error`` flag fails here
regardless of which SDK generation introduced the change.

Both transports (stdio and streamable HTTP) and both protocol eras are covered:
``legacy`` is the 2025-era handshake that current Claude Desktop builds use,
``auto`` resolves to the 2026-07-28 per-request path that SDK 2.x prefers.
"""

from unittest.mock import AsyncMock

import pytest
from mcp.client import Client
from mcp.types import TextContent

from kimai_mcp import __version__
from kimai_mcp.client import KimaiAPIError, KimaiClient
from kimai_mcp.server import KimaiMCPServer
from kimai_mcp.streamable_http_server import UserMCPSession
from kimai_mcp.tools.errors import ToolError
from kimai_mcp.tools.registry import tool_names
from kimai_mcp.user_config import UserConfig

EXPECTED_TOOL_COUNT = 12

LIST_ARGS = {"type": "project", "action": "list"}


def _local_server() -> KimaiMCPServer:
    # KimaiClient connects lazily, so nothing here touches the network.
    return KimaiMCPServer(base_url="http://example.invalid", api_token="t")


def _user_session() -> UserMCPSession:
    config = UserConfig(kimai_url="http://example.invalid", kimai_token="t")
    return UserMCPSession("alice", config)


def _raise(exc):
    async def _dispatch(client, name, arguments):
        raise exc

    return _dispatch


@pytest.fixture(params=["stdio", "streamable"])
def transport(request):
    """The low-level Server of each transport, with a stubbed Kimai client.

    Returns (server, dispatch_path) where dispatch_path is the module attribute
    to monkeypatch in order to control what the tool handler does.
    """
    if request.param == "stdio":
        server = _local_server()
        server.client = AsyncMock(spec=KimaiClient)
        return server.server, "kimai_mcp.server.dispatch_tool"

    session = _user_session()
    session.kimai_client = AsyncMock(spec=KimaiClient)
    return session.mcp_server, "kimai_mcp.streamable_http_server.dispatch_tool"


@pytest.fixture(params=["legacy", "auto"])
def mode(request):
    """Protocol era: the 2025 handshake and the 2026-07-28 per-request path."""
    return request.param


@pytest.mark.asyncio
async def test_handshake_and_tool_listing(transport, mode):
    """A client can connect and list all 12 consolidated tools."""
    server, _ = transport

    async with Client(server, mode=mode) as client:
        result = await client.list_tools()

    names = [tool.name for tool in result.tools]
    assert names == tool_names()
    assert len(names) == EXPECTED_TOOL_COUNT
    for tool in result.tools:
        assert tool.description, f"{tool.name} must describe itself to the model"
        assert tool.input_schema.get("type") == "object"


@pytest.mark.asyncio
async def test_successful_tool_call_is_not_an_error(transport, mode, monkeypatch):
    """A handler's content list reaches the client as a successful result.

    SDK 2.x stopped wrapping bare handler return values, so a missing
    ``CallToolResult`` wrapper would surface here.
    """
    server, dispatch_path = transport

    async def _ok(client, name, arguments):
        return [TextContent(type="text", text="2 project(s) found")]

    monkeypatch.setattr(dispatch_path, _ok)

    async with Client(server, mode=mode) as client:
        result = await client.call_tool("entity", LIST_ARGS)

    assert result.is_error is False
    assert result.content[0].text == "2 project(s) found"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ToolError("Error: bad input"), "Error: bad input"),
        (KimaiAPIError("nope", status_code=403), "lacks permission"),
        (RuntimeError("boom"), "Error: boom"),
    ],
    ids=["tool_error", "api_error", "unexpected"],
)
async def test_tool_failures_reach_the_client_as_is_error(
    transport, mode, monkeypatch, exc, expected
):
    """Tool failures arrive as a result with is_error set, not a protocol error."""
    server, dispatch_path = transport
    monkeypatch.setattr(dispatch_path, _raise(exc))

    async with Client(server, mode=mode) as client:
        result = await client.call_tool("entity", LIST_ARGS)

    assert result.is_error is True
    assert expected in "\n".join(c.text for c in result.content)


@pytest.mark.asyncio
async def test_unknown_tool_is_reported_as_is_error(transport, mode):
    """An unknown tool name is a tool error, not a crash."""
    server, _ = transport

    async with Client(server, mode=mode) as client:
        result = await client.call_tool("does_not_exist", {})

    assert result.is_error is True
    assert "Unknown tool" in "\n".join(c.text for c in result.content)


@pytest.mark.asyncio
async def test_server_advertises_tool_capability_and_version(transport, mode):
    """The connection exposes the tools capability and the package version."""
    server, _ = transport

    async with Client(server, mode=mode) as client:
        assert client.server_capabilities.tools is not None
        assert client.server_info.version == __version__
