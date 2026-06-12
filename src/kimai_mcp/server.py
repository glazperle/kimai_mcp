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

from kimai_mcp import __version__

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

# Shared tool registry (single source of truth for both servers)
from .tools.registry import all_tools, dispatch_tool

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def format_api_error(e: KimaiAPIError) -> str:
    """Format a KimaiAPIError for the MCP client, including validation details."""
    text = f"Kimai API Error: {e.message} (Status: {e.status_code})"
    if e.status_code == 403:
        text += "\nThe API token lacks permission for this operation (Kimai enforces team/user permissions strictly)."
    if e.details:
        text += f"\nDetails: {json.dumps(e.details, ensure_ascii=False, default=str)}"
    return text


class KimaiMCPServer:
    """Kimai MCP Server with consolidated tools (73 → 12 tools)."""

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
        if default_user_id or os.getenv("KIMAI_DEFAULT_USER"):
            logger.warning(
                "default_user_id (--kimai-user / KIMAI_DEFAULT_USER) is deprecated and has no effect; "
                "use the user_scope parameter of the individual tools instead."
            )

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
        """List consolidated MCP tools (12 tools instead of the original 73)."""
        return all_tools()

    async def _call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
        """Handle consolidated tool calls."""
        await self._ensure_client()

        # Ensure arguments is not None
        if arguments is None:
            arguments = {}

        try:
            # Route to the shared tool registry
            return await dispatch_tool(self.client, name, arguments)

        except KimaiAPIError as e:
            logger.error(f"Kimai API Error in tool {name}: {e.message} (Status: {e.status_code})")
            logger.error(f"Arguments were: {arguments}")
            return [TextContent(
                type="text",
                text=format_api_error(e)
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
                f"Connected to Kimai {version.version} with 12 consolidated tools")
        except Exception as e:
            logger.error(f"Failed to connect to Kimai: {str(e)}")
            raise

        # Configure server options
        options = InitializationOptions(
            server_name="kimai-mcp-consolidated",
            server_version=__version__,
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
        help="Deprecated, has no effect (kept for backward compatibility)"
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

    ssl_verify = input("  SSL Verify (true/false/path, default: true): ").strip() or "true"

    # Build config
    args = [f"--kimai-url={kimai_url}", f"--kimai-token={api_token}"]
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
