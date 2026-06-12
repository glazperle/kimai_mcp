"""Configuration and system info tool for Kimai."""

import asyncio
from typing import List
from mcp.types import Tool, TextContent
from ..client import KimaiClient


def config_tool() -> Tool:
    """Define the configuration info tool."""
    return Tool(
        name="config",
        description="Fetch Kimai server configuration, installed plugins, and system info. Useful for understanding server rules and capabilities.",
        inputSchema={
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["timesheet", "colors", "plugins", "version", "all"],
                    "description": """Type of configuration to fetch:
                    - timesheet: Tracking mode, limits, overlapping rules
                    - colors: Available color codes and names
                    - plugins: Installed plugins and versions
                    - version: Kimai version information
                    - all: Fetch all configuration info
                    """
                }
            }
        }
    )


async def handle_config(client: KimaiClient, **params) -> List[TextContent]:
    """Handle configuration info requests."""
    config_type = params.get("type", "all")

    # Errors propagate to the central handler in server.py
    if config_type == "timesheet":
        return await _handle_timesheet_config(client)
    elif config_type == "colors":
        return await _handle_color_config(client)
    elif config_type == "plugins":
        return await _handle_plugins(client)
    elif config_type == "version":
        return await _handle_version(client)
    elif config_type == "all":
        return await _handle_all_config(client)
    else:
        return [TextContent(
            type="text",
            text=f"Error: Unknown config type '{config_type}'. Valid types: timesheet, colors, plugins, version, all"
        )]


async def _handle_timesheet_config(client: KimaiClient) -> List[TextContent]:
    """Get timesheet configuration."""
    config = await client.get_timesheet_config()

    result = "Timesheet Configuration:\n\n"
    result += f"  Tracking Mode: {config.tracking_mode}\n"
    result += f"  Default Begin Time: {config.default_begin_time}\n"
    result += f"  Active Entries Limit: {config.active_entries_hard_limit}\n"
    result += f"  Allow Future Times: {config.is_allow_future_times}\n"
    result += f"  Allow Overlapping: {config.is_allow_overlapping}\n"

    # Add helpful notes based on config
    result += "\nNotes:\n"
    if not config.is_allow_overlapping:
        result += "  ⚠️ Overlapping time entries are NOT allowed\n"
    if not config.is_allow_future_times:
        result += "  ⚠️ Future time entries are NOT allowed\n"
    if config.active_entries_hard_limit == 1:
        result += "  ℹ️ Only one active timer allowed at a time\n"

    return [TextContent(type="text", text=result)]


async def _handle_color_config(client: KimaiClient) -> List[TextContent]:
    """Get color configuration."""
    colors = await client.get_color_config()

    if not colors:
        return [TextContent(type="text", text="No custom colors configured.")]

    result = "Available Colors:\n\n"
    for name, hex_code in colors.items():
        result += f"  {name}: {hex_code}\n"

    return [TextContent(type="text", text=result)]


async def _handle_plugins(client: KimaiClient) -> List[TextContent]:
    """Get installed plugins."""
    plugins = await client.get_plugins()

    if not plugins:
        return [TextContent(type="text", text="No plugins installed.")]

    result = f"Installed Plugins ({len(plugins)}):\n\n"
    for plugin in plugins:
        result += f"  {plugin.name}: v{plugin.version}\n"

    return [TextContent(type="text", text=result)]


async def _handle_version(client: KimaiClient) -> List[TextContent]:
    """Get version information."""
    version = await client.get_version()

    result = "Kimai Version:\n\n"
    result += f"  Version: {version.version}\n"
    result += f"  Version ID: {version.version_id}\n"
    result += f"  {version.copyright}\n"

    return [TextContent(type="text", text=result)]


async def _handle_all_config(client: KimaiClient) -> List[TextContent]:
    """Get all configuration info (fetched in parallel)."""
    version_result, ts_result, plugin_result, color_result = await asyncio.gather(
        _handle_version(client),
        _handle_timesheet_config(client),
        _handle_plugins(client),
        _handle_color_config(client),
        return_exceptions=True,
    )

    results = []

    # Version
    if isinstance(version_result, BaseException):
        results.append(TextContent(type="text", text=f"Version error: {version_result}"))
    else:
        results.extend(version_result)

    # Timesheet config
    if isinstance(ts_result, BaseException):
        results.append(TextContent(type="text", text=f"Timesheet config error: {ts_result}"))
    else:
        results.append(TextContent(type="text", text="\n---\n"))
        results.extend(ts_result)

    # Plugins
    if isinstance(plugin_result, BaseException):
        results.append(TextContent(type="text", text=f"Plugins error: {plugin_result}"))
    else:
        results.append(TextContent(type="text", text="\n---\n"))
        results.extend(plugin_result)

    # Colors (optional, may not be configured - errors are ignored)
    if not isinstance(color_result, BaseException):
        results.append(TextContent(type="text", text="\n---\n"))
        results.extend(color_result)

    return results
