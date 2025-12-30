"""Kimai MCP Server implementation with consolidated tools."""

import argparse
import asyncio
import json
import logging
import os
import platform
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

__version__ = "2.8.0"

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
                 default_user_id: Optional[str] = None,
                 ssl_verify: Optional[Union[bool, str]] = None):
        """Initialize the consolidated Kimai MCP server.

        Args:
            base_url: Kimai server URL (can also be set via KIMAI_URL env var)
            api_token: API authentication token (can also be set via KIMAI_API_TOKEN env var)
            default_user_id: Default user ID for operations (can also be set via KIMAI_DEFAULT_USER env var)
            ssl_verify: SSL verification setting (can also be set via KIMAI_SSL_VERIFY env var):
                - True: Use default CA bundle (default)
                - False: Disable SSL verification (not recommended)
                - str: Path to CA certificate file or directory
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

        # SSL verification - prefer argument, fallback to environment variable
        if ssl_verify is not None:
            self.ssl_verify = ssl_verify
        else:
            ssl_env = os.getenv("KIMAI_SSL_VERIFY", "true").lower()
            if ssl_env == "true":
                self.ssl_verify = True
            elif ssl_env == "false":
                self.ssl_verify = False
                logger.warning("SSL verification is disabled. This is not recommended for production use.")
            else:
                # Treat as path to certificate
                self.ssl_verify = ssl_env

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
            self.client = KimaiClient(self.base_url, self.api_token, ssl_verify=self.ssl_verify)

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


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for CLI."""
    parser = argparse.ArgumentParser(
        prog="kimai-mcp",
        description="Kimai MCP Server - Time-tracking API integration for Claude Desktop and other MCP clients",
        epilog="Documentation: https://github.com/glazperle/kimai_mcp",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--kimai-url",
        metavar="URL",
        help="Kimai server URL (e.g., https://kimai.example.com)"
    )
    parser.add_argument(
        "--kimai-token",
        metavar="TOKEN",
        help="API authentication token from your Kimai user profile"
    )
    parser.add_argument(
        "--kimai-user",
        metavar="USER_ID",
        help="Default user ID for operations (optional)"
    )
    parser.add_argument(
        "--ssl-verify",
        metavar="VALUE",
        default="true",
        help="SSL verification: 'true' (default), 'false', or path to CA certificate"
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Interactive setup wizard for Claude Desktop configuration"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}"
    )
    return parser


def get_claude_config_path() -> Path:
    """Get Claude Desktop config path based on OS."""
    system = platform.system()
    if system == "Darwin":  # macOS
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "Claude" / "claude_desktop_config.json"
        return Path.home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    else:  # Linux and others
        return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def write_config_to_file(config_path: Path, new_config: dict) -> bool:
    """Write config to file, merging with existing and creating backup.

    Returns True on success, False on failure.
    """
    try:
        # Create directory if needed
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing config or start fresh
        existing = {}
        if config_path.exists():
            # Create backup
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = config_path.with_suffix(f".backup-{timestamp}.json")
            shutil.copy(config_path, backup_path)
            print(f"  Backup created: {backup_path}")

            with open(config_path, "r", encoding="utf-8") as f:
                existing = json.load(f)

        # Merge mcpServers
        if "mcpServers" not in existing:
            existing["mcpServers"] = {}
        existing["mcpServers"]["kimai"] = new_config["mcpServers"]["kimai"]

        # Write merged config
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        print(f"  Configuration written to: {config_path}")
        return True
    except Exception as e:
        print(f"  Error writing config: {e}")
        return False


def interactive_setup():
    """Interactive setup wizard for Claude Desktop configuration."""
    print()
    print("=" * 50)
    print("   Kimai MCP Server - Setup Wizard")
    print("=" * 50)
    print()

    # Collect configuration
    print("Enter your Kimai configuration:")
    print()

    kimai_url = input("  Kimai Server URL: ").strip()
    if not kimai_url:
        print("\n  Error: Kimai URL is required.")
        return

    api_token = input("  API Token: ").strip()
    if not api_token:
        print("\n  Error: API Token is required.")
        return

    user_id = input("  Default User ID (optional, press Enter to skip): ").strip() or None
    ssl_verify = input("  SSL Verify (true/false/path, default: true): ").strip() or "true"

    # Build config
    args = [f"--kimai-url={kimai_url}", f"--kimai-token={api_token}"]
    if user_id:
        args.append(f"--kimai-user={user_id}")
    if ssl_verify.lower() != "true":
        args.append(f"--ssl-verify={ssl_verify}")

    config = {
        "mcpServers": {
            "kimai": {
                "command": "kimai-mcp",
                "args": args
            }
        }
    }

    # Show config
    config_path = get_claude_config_path()
    print()
    print("-" * 50)
    print("  Claude Desktop config location:")
    print(f"  {config_path}")
    print("-" * 50)
    print()
    print("  Configuration to add:")
    print()
    print(json.dumps(config, indent=2))
    print()

    # Offer to write config
    write = input("  Write to config file? (y/N): ").strip().lower()
    if write == "y":
        print()
        if write_config_to_file(config_path, config):
            print()
            print("  Restart Claude Desktop to apply changes.")
        else:
            print()
            print("  Please add the configuration manually.")
    else:
        print()
        print("  Configuration not written. Add it manually to your config file.")

    print()


async def main():
    """Main entry point for consolidated server."""
    parser = create_parser()
    args = parser.parse_args()

    # Handle setup wizard
    if args.setup:
        interactive_setup()
        return

    # Parse SSL verify value
    ssl_verify: Optional[Union[bool, str]] = None
    if args.ssl_verify:
        ssl_value = args.ssl_verify.lower()
        if ssl_value == "true":
            ssl_verify = True
        elif ssl_value == "false":
            ssl_verify = False
        else:
            # Treat as path to certificate file/directory
            ssl_verify = args.ssl_verify

    server = KimaiMCPServer(
        base_url=args.kimai_url,
        api_token=args.kimai_token,
        default_user_id=args.kimai_user,
        ssl_verify=ssl_verify
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
