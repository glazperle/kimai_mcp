"""Kimai MCP Server implementation with consolidated tools."""

import asyncio
import logging
import os
import sys
from typing import Any, Dict, List, Optional

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.types import Tool, TextContent
from .client import KimaiClient, KimaiAPIError

# Import consolidated tools
from .tools.entity_manager import entity_tool, handle_entity
from .tools.timesheet_consolidated import timesheet_tool, timer_tool, handle_timesheet, handle_timer
from .tools.rate_manager import rate_tool, handle_rate
from .tools.team_access_manager import team_access_tool, handle_team_access
from .tools.absence_manager import absence_tool, handle_absence
from .tools.calendar_meta import calendar_tool, meta_tool, user_current_tool, handle_calendar, handle_meta, \
    handle_user_current
from .tools.project_analysis import analyze_project_team_tool, handle_analyze_project_team
from .tools.config_info import config_tool, handle_config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KimaiMCPServer:
    """Kimai MCP Server with consolidated tools (73 → 10 tools)."""

    def __init__(self, base_url: Optional[str] = None, api_token: Optional[str] = None,
                 default_user_id: Optional[str] = None):
        """Initialize the consolidated Kimai MCP server.
        
        Args:
            base_url: Kimai server URL (can also be set via KIMAI_URL env var)
            api_token: API authentication token (can also be set via KIMAI_API_TOKEN env var)
            default_user_id: Default user ID for operations (can also be set via KIMAI_DEFAULT_USER env var)
        """
        self.server = Server("kimai-mcp-consolidated")
        self.client: Optional[KimaiClient] = None

        # Register handlers
        self.server.list_tools()(self._list_tools)
        self.server.call_tool()(self._call_tool)

        # Configuration - prefer arguments, fallback to environment variables
        self.base_url = (base_url or os.getenv("KIMAI_URL", "")).rstrip('/')
        self.api_token = api_token or os.getenv("KIMAI_API_TOKEN", "")
        self.default_user_id = default_user_id or os.getenv("KIMAI_DEFAULT_USER")

        # Validate configuration
        if not self.base_url:
            raise ValueError(
                "Kimai URL is required (provide via constructor argument or KIMAI_URL environment variable)")
        if not self.api_token:
            raise ValueError(
                "Kimai API token is required (provide via constructor argument or KIMAI_API_TOKEN environment variable)")

    async def _ensure_client(self):
        """Ensure the Kimai client is initialized."""
        if not self.client:
            self.client = KimaiClient(self.base_url, self.api_token)

    async def _list_tools(self) -> List[Tool]:
        """List consolidated MCP tools (10 tools instead of 73)."""
        return [
            # Universal Entity Manager (replaces 35 tools)
            entity_tool(),

            # Timesheet Management (replaces 9 tools)
            timesheet_tool(),

            # Timer Management (replaces 4 tools)
            timer_tool(),

            # Rate Management (replaces 9 tools)
            rate_tool(),

            # Team Access Management (replaces 8 tools)
            team_access_tool(),

            # Absence Management (replaces 6 tools)
            absence_tool(),

            # Calendar Tool (replaces 2 tools)
            calendar_tool(),

            # Meta Fields Management (replaces 4 tools)
            meta_tool(),

            # Current User (specialized tool)
            user_current_tool(),

            # Project Analysis (specialized tool, kept as-is)
            analyze_project_team_tool(),

            # Configuration Info (server config, plugins, version)
            config_tool(),
        ]

    async def _call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
        """Handle consolidated tool calls."""
        await self._ensure_client()

        # Ensure arguments is not None
        if arguments is None:
            arguments = {}

        try:
            # Route to consolidated tool handlers
            if name == "entity":
                return await handle_entity(self.client, **arguments)
            elif name == "timesheet":
                return await handle_timesheet(self.client, **arguments)
            elif name == "timer":
                return await handle_timer(self.client, **arguments)
            elif name == "rate":
                return await handle_rate(self.client, **arguments)
            elif name == "team_access":
                return await handle_team_access(self.client, **arguments)
            elif name == "absence":
                return await handle_absence(self.client, **arguments)
            elif name == "calendar":
                return await handle_calendar(self.client, **arguments)
            elif name == "meta":
                return await handle_meta(self.client, **arguments)
            elif name == "user_current":
                return await handle_user_current(self.client, **arguments)
            elif name == "analyze_project_team":
                return await handle_analyze_project_team(self.client, arguments)
            elif name == "config":
                return await handle_config(self.client, **arguments)
            else:
                return [TextContent(
                    type="text",
                    text=f"Unknown tool: {name}. Available tools: entity, timesheet, timer, rate, team_access, absence, calendar, meta, user_current, analyze_project_team, config"
                )]

        except KimaiAPIError as e:
            logger.error(f"Kimai API Error in tool {name}: {e.message} (Status: {e.status_code})")
            logger.error(f"Arguments were: {arguments}")
            return [TextContent(
                type="text",
                text=f"Kimai API Error: {e.message} (Status: {e.status_code})"
            )]
        except Exception as e:
            logger.error(f"Error calling tool {name}: {str(e)}", exc_info=True)
            logger.error(f"Arguments were: {arguments}")
            return [TextContent(
                type="text",
                text=f"Error: {str(e)}"
            )]

    async def run(self):
        """Run the consolidated MCP server."""
        # Initialize client
        await self._ensure_client()

        # Verify connection
        try:
            version = await self.client.get_version()
            logger.info(
                f"Connected to Kimai {version.version} with 10 consolidated tools (87% reduction from 73 tools)")
        except Exception as e:
            logger.error(f"Failed to connect to Kimai: {str(e)}")
            raise

        # Configure server options
        options = InitializationOptions(
            server_name="kimai-mcp-consolidated",
            server_version="2.0.0",
            capabilities=self.server.get_capabilities(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            ),
        )

        # Run the server
        from mcp.server.stdio import stdio_server
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                options
            )

    async def cleanup(self):
        """Clean up resources."""
        if self.client:
            await self.client.close()


async def main():
    """Main entry point for consolidated server."""
    # Get configuration from command line arguments if provided
    # This allows configuration to be passed from MCP client (like Claude Desktop)
    base_url = None
    api_token = None
    default_user_id = None

    # Parse command line arguments for configuration
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.startswith("--kimai-url="):
                base_url = arg.split("=", 1)[1]
            elif arg.startswith("--kimai-token="):
                api_token = arg.split("=", 1)[1]
            elif arg.startswith("--kimai-user="):
                default_user_id = arg.split("=", 1)[1]

    server = KimaiMCPServer(
        base_url=base_url,
        api_token=api_token,
        default_user_id=default_user_id
    )
    try:
        await server.run()
    finally:
        await server.cleanup()


def entrypoint():
    """Separate non async entrypoint for pyproject.toml script entrypoint."""
    asyncio.run(main())


if __name__ == "__main__":
    entrypoint()
