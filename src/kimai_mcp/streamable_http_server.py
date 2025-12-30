"""Streamable HTTP server for Claude.ai Connectors with multi-user support.

This server implements the MCP Streamable HTTP transport specification,
allowing it to work as a remote MCP server with Claude.ai Connectors.

Each user gets their own endpoint (/mcp/{user_slug}) with their own
Kimai credentials configured server-side.
"""

import argparse
import contextlib
import logging
import re
from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool, TextContent

from .client import KimaiClient, KimaiAPIError
from .server import __version__
from .user_config import UsersConfig, UserConfig

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


class UserMCPSession:
    """MCP session for a single user with their own Kimai credentials."""

    def __init__(self, user_slug: str, config: UserConfig):
        """Initialize user session.

        Args:
            user_slug: User identifier (used in URL path)
            config: User's Kimai configuration
        """
        self.user_slug = user_slug
        self.config = config
        self.kimai_client: Optional[KimaiClient] = None

        # Create MCP server for this user
        self.mcp_server = Server(f"kimai-mcp-{user_slug}")

        # Register tool handlers
        self.mcp_server.list_tools()(self._list_tools)
        self.mcp_server.call_tool()(self._call_tool)

        # Session manager (created during initialization)
        self.session_manager: Optional[StreamableHTTPSessionManager] = None

    async def initialize(self) -> None:
        """Initialize the Kimai client and verify connection."""
        self.kimai_client = KimaiClient(
            base_url=self.config.kimai_url,
            api_token=self.config.kimai_token,
            ssl_verify=self.config.ssl_verify,
        )

        # Verify connection
        try:
            version = await self.kimai_client.get_version()
            logger.info(
                f"User '{self.user_slug}' connected to Kimai {version.version} at {self.config.kimai_url}"
            )
        except Exception as e:
            logger.error(f"Failed to connect for user '{self.user_slug}': {e}")
            raise

        # Create session manager
        self.session_manager = StreamableHTTPSessionManager(
            app=self.mcp_server,
            json_response=False,  # Use SSE for streaming
            stateless=False,  # Stateful for better performance
        )

    async def cleanup(self) -> None:
        """Clean up resources."""
        if self.kimai_client:
            await self.kimai_client.close()
            self.kimai_client = None

    async def _list_tools(self) -> List[Tool]:
        """List all available MCP tools."""
        return [
            entity_tool(),
            timesheet_tool(),
            timer_tool(),
            rate_tool(),
            team_access_tool(),
            absence_tool(),
            calendar_tool(),
            meta_tool(),
            user_current_tool(),
            analyze_project_team_tool(),
            config_tool(),
        ]

    async def _call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
        """Handle tool calls."""
        if self.kimai_client is None:
            return [TextContent(type="text", text="Error: Kimai client not initialized")]

        arguments = arguments or {}

        try:
            if name == "entity":
                return await handle_entity(self.kimai_client, **arguments)
            elif name == "timesheet":
                return await handle_timesheet(self.kimai_client, **arguments)
            elif name == "timer":
                return await handle_timer(self.kimai_client, **arguments)
            elif name == "rate":
                return await handle_rate(self.kimai_client, **arguments)
            elif name == "team_access":
                return await handle_team_access(self.kimai_client, **arguments)
            elif name == "absence":
                return await handle_absence(self.kimai_client, **arguments)
            elif name == "calendar":
                return await handle_calendar(self.kimai_client, **arguments)
            elif name == "meta":
                return await handle_meta(self.kimai_client, **arguments)
            elif name == "user_current":
                return await handle_user_current(self.kimai_client, **arguments)
            elif name == "analyze_project_team":
                return await handle_analyze_project_team(self.kimai_client, arguments)
            elif name == "config":
                return await handle_config(self.kimai_client, **arguments)
            else:
                return [TextContent(
                    type="text",
                    text=f"Unknown tool: {name}"
                )]

        except KimaiAPIError as e:
            logger.error(f"Kimai API Error for user '{self.user_slug}' in tool {name}: {e.message}")
            return [TextContent(type="text", text=f"Kimai API Error: {e.message} (Status: {e.status_code})")]
        except Exception as e:
            logger.error(f"Error for user '{self.user_slug}' calling tool {name}: {e}", exc_info=True)
            return [TextContent(type="text", text=f"Error: {str(e)}")]


class MCPRoutingMiddleware:
    """ASGI Middleware that routes /mcp/{user_slug} requests to the appropriate session manager.

    The StreamableHTTPSessionManager requires direct ASGI access (scope, receive, send),
    so we intercept MCP requests before they reach Starlette's router.
    """

    # Pattern to match /mcp/{user_slug} paths
    MCP_PATH_PATTERN = re.compile(r"^/mcp/([a-zA-Z0-9_-]+)$")

    def __init__(self, app: ASGIApp, user_sessions: Dict[str, UserMCPSession]):
        """Initialize middleware.

        Args:
            app: The wrapped ASGI application (Starlette)
            user_sessions: Dictionary of user slug to session
        """
        self.app = app
        self.user_sessions = user_sessions

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle ASGI request."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        match = self.MCP_PATH_PATTERN.match(path)

        if match:
            user_slug = match.group(1)
            await self._handle_mcp_request(scope, receive, send, user_slug)
        else:
            # Pass through to Starlette for other routes
            await self.app(scope, receive, send)

    async def _handle_mcp_request(
        self, scope: Scope, receive: Receive, send: Send, user_slug: str
    ) -> None:
        """Handle MCP request for a specific user."""
        if user_slug not in self.user_sessions:
            response = JSONResponse(
                {"error": f"User not found: {user_slug}"},
                status_code=404,
            )
            await response(scope, receive, send)
            return

        session = self.user_sessions[user_slug]
        if not session.session_manager:
            response = JSONResponse(
                {"error": "Session not initialized"},
                status_code=500,
            )
            await response(scope, receive, send)
            return

        # Delegate to the user's session manager
        await session.session_manager.handle_request(scope, receive, send)


class StreamableHTTPMCPServer:
    """Multi-user Streamable HTTP MCP server for Claude.ai Connectors."""

    def __init__(
        self,
        users_config: UsersConfig,
        host: str = "0.0.0.0",
        port: int = 8000,
    ):
        """Initialize the server.

        Args:
            users_config: Configuration for all users
            host: Host to bind to
            port: Port to bind to
        """
        self.users_config = users_config
        self.host = host
        self.port = port
        self.user_sessions: Dict[str, UserMCPSession] = {}

    async def initialize_users(self) -> None:
        """Initialize all user sessions."""
        for slug, config in self.users_config.users.items():
            try:
                session = UserMCPSession(slug, config)
                await session.initialize()
                self.user_sessions[slug] = session
                logger.info(f"Initialized session for user '{slug}'")
            except Exception as e:
                logger.error(f"Failed to initialize user '{slug}': {e}")
                # Continue with other users

        if not self.user_sessions:
            raise RuntimeError("No user sessions could be initialized")

    async def cleanup_users(self) -> None:
        """Clean up all user sessions."""
        for slug, session in self.user_sessions.items():
            try:
                await session.cleanup()
                logger.info(f"Cleaned up session for user '{slug}'")
            except Exception as e:
                logger.error(f"Error cleaning up user '{slug}': {e}")

    @contextlib.asynccontextmanager
    async def lifespan(self, app: Starlette) -> AsyncIterator[None]:
        """Manage server lifecycle."""
        logger.info(f"Starting Streamable HTTP MCP server on {self.host}:{self.port}")
        logger.info(f"Version: {__version__}")

        # Initialize users
        await self.initialize_users()

        # Start all session managers
        async with contextlib.AsyncExitStack() as stack:
            for slug, session in self.user_sessions.items():
                if session.session_manager:
                    await stack.enter_async_context(session.session_manager.run())
                    logger.info(f"Started session manager for user '{slug}'")

            logger.info(f"Server ready with {len(self.user_sessions)} user endpoint(s)")
            logger.info(f"Endpoints: {', '.join(f'/mcp/{s}' for s in self.user_sessions.keys())}")

            yield

        # Cleanup
        logger.info("Shutting down...")
        await self.cleanup_users()

    async def health_check(self, request: Request) -> JSONResponse:
        """Health check endpoint."""
        return JSONResponse({
            "status": "healthy",
            "version": __version__,
            "transport": "streamable-http",
            "users": list(self.user_sessions.keys()),
            "active_sessions": len(self.user_sessions),
        })

    async def list_users(self, request: Request) -> JSONResponse:
        """List available user endpoints."""
        base_url = str(request.base_url).rstrip("/")
        return JSONResponse({
            "users": [
                {
                    "slug": slug,
                    "endpoint": f"{base_url}/mcp/{slug}",
                    "kimai_url": self.users_config.users[slug].kimai_url,
                }
                for slug in self.user_sessions.keys()
            ]
        })

    async def root(self, request: Request) -> JSONResponse:
        """Root endpoint with server info."""
        base_url = str(request.base_url).rstrip("/")
        return JSONResponse({
            "name": "Kimai MCP Server",
            "version": __version__,
            "transport": "streamable-http",
            "endpoints": {
                "health": f"{base_url}/health",
                "users": f"{base_url}/users",
                "mcp": f"{base_url}/mcp/{{user_slug}}",
            },
            "documentation": "https://github.com/glazperle/kimai_mcp",
        })

    def create_app(self) -> ASGIApp:
        """Create the ASGI application with MCP routing middleware."""
        # Create Starlette app for non-MCP routes
        routes = [
            Route("/", endpoint=self.root, methods=["GET"]),
            Route("/health", endpoint=self.health_check, methods=["GET"]),
            Route("/users", endpoint=self.list_users, methods=["GET"]),
        ]

        starlette_app = Starlette(
            routes=routes,
            lifespan=self.lifespan,
        )

        # Wrap with MCP routing middleware
        return MCPRoutingMiddleware(starlette_app, self.user_sessions)

    def run(self) -> None:
        """Run the server."""
        try:
            import uvicorn
        except ImportError:
            raise ImportError(
                "uvicorn is required for the HTTP server. "
                "Install with: pip install kimai-mcp[server]"
            )

        app = self.create_app()
        uvicorn.run(
            app,
            host=self.host,
            port=self.port,
            log_level="info",
        )


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for CLI."""
    parser = argparse.ArgumentParser(
        prog="kimai-mcp-streamable",
        description="Kimai MCP Streamable HTTP Server for Claude.ai Connectors",
        epilog="Documentation: https://github.com/glazperle/kimai_mcp",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind server to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind server to (default: 8000)",
    )
    parser.add_argument(
        "--users-config",
        metavar="FILE",
        help="Path to users.json config file (or set USERS_CONFIG_FILE env var)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser


def main() -> int:
    """Main entry point."""
    # Load environment variables
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = create_parser()
    args = parser.parse_args()

    try:
        # Load users config
        users_config = UsersConfig.load(args.users_config)
        logger.info(f"Loaded configuration for {len(users_config.users)} user(s)")

        # Create and run server
        server = StreamableHTTPMCPServer(
            users_config=users_config,
            host=args.host,
            port=args.port,
        )
        server.run()
        return 0

    except FileNotFoundError as e:
        logger.error(f"Config file not found: {e}")
        return 1
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit(main())
