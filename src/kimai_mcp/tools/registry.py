"""Shared tool registry consumed by both the stdio and streamable HTTP servers.

Having a single source of truth for the tool list and the name->handler dispatch
prevents the two servers from drifting apart (e.g. a tool registered in one but
not the other).
"""
from typing import Any, Dict, List, Optional

from mcp.types import Tool, TextContent

from ..client import KimaiClient
from .errors import ToolError
from .entity_manager import entity_tool, handle_entity
from .timesheet_consolidated import timesheet_tool, timer_tool, handle_timesheet, handle_timer
from .rate_manager import rate_tool, handle_rate
from .team_access_manager import team_access_tool, handle_team_access
from .absence_manager import absence_tool, handle_absence
from .calendar_meta import (
    calendar_tool, meta_tool, user_current_tool,
    handle_calendar, handle_meta, handle_user_current,
)
from .project_analysis import analyze_project_team_tool, handle_analyze_project_team
from .config_info import config_tool, handle_config
from .comment_tool import comment_tool, handle_comment


def _kw(handler):
    """Adapter for handlers called as handler(client, **arguments)."""
    async def _run(client, arguments):
        return await handler(client, **arguments)
    return _run


def _positional(handler):
    """Adapter for handlers called as handler(client, arguments)."""
    async def _run(client, arguments):
        return await handler(client, arguments)
    return _run


# Ordered name -> (tool factory, dispatch adapter). Insertion order defines the
# order in which tools are advertised to the MCP client.
_REGISTRY = {
    "entity": (entity_tool, _kw(handle_entity)),
    "timesheet": (timesheet_tool, _kw(handle_timesheet)),
    "timer": (timer_tool, _kw(handle_timer)),
    "rate": (rate_tool, _kw(handle_rate)),
    "team_access": (team_access_tool, _kw(handle_team_access)),
    "absence": (absence_tool, _kw(handle_absence)),
    "calendar": (calendar_tool, _kw(handle_calendar)),
    "meta": (meta_tool, _kw(handle_meta)),
    "user_current": (user_current_tool, _kw(handle_user_current)),
    "analyze_project_team": (analyze_project_team_tool, _positional(handle_analyze_project_team)),
    "config": (config_tool, _kw(handle_config)),
    "comment": (comment_tool, _kw(handle_comment)),
}


def all_tools() -> List[Tool]:
    """Return the full list of Tool definitions, in advertised order."""
    return [factory() for factory, _ in _REGISTRY.values()]


def tool_names() -> List[str]:
    """Return the registered tool names."""
    return list(_REGISTRY.keys())


async def dispatch_tool(
    client: KimaiClient, name: str, arguments: Optional[Dict[str, Any]]
) -> List[TextContent]:
    """Route a tool call to its handler. Exceptions propagate to the caller's
    error handling (ToolError / KimaiAPIError -> error_result)."""
    entry = _REGISTRY.get(name)
    if entry is None:
        raise ToolError(
            f"Unknown tool: {name}. Available tools: {', '.join(_REGISTRY)}"
        )
    _, run = entry
    return await run(client, arguments or {})
