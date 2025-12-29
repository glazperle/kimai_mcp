"""HTTP/SSE server for remote MCP access with authentication."""

import argparse
import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from typing import Any, Optional, Union

try:
    import uvicorn
    from fastapi import FastAPI, Header, HTTPException, Request
    from fastapi.responses import StreamingResponse
    from starlette.middleware.cors import CORSMiddleware
    from sse_starlette import EventSourceResponse
except ImportError as e:
    raise ImportError(
        "Remote server dependencies not installed. "
        "Install with: pip install kimai-mcp[server]"
    ) from e

from mcp.server.sse import SseServerTransport
from .server import KimaiMCPServer, __version__

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails."""
    pass


class RemoteMCPServer:
    """Remote MCP server with HTTP/SSE transport and authentication."""

    def __init__(
        self,
        kimai_url: str,
        kimai_token: str,
        kimai_user: Optional[str] = None,
        ssl_verify: Optional[Union[bool, str]] = None,
        server_token: Optional[str] = None,
        host: str = "0.0.0.0",
        port: int = 8000,
        allowed_origins: Optional[list[str]] = None,
    ):
        """Initialize the remote MCP server.

        Args:
            kimai_url: Kimai server URL
            kimai_token: Kimai API token
            kimai_user: Default Kimai user ID
            ssl_verify: SSL verification setting for Kimai connection
            server_token: Authentication token for MCP server access (generated if not provided)
            host: Host to bind the server to
            port: Port to bind the server to
            allowed_origins: List of allowed CORS origins
        """
        self.kimai_url = kimai_url
        self.kimai_token = kimai_token
        self.kimai_user = kimai_user
        self.ssl_verify = ssl_verify
        self.host = host
        self.port = port
        self.allowed_origins = allowed_origins or ["*"]

        # Generate or use provided server token
        self.server_token = server_token or secrets.token_urlsafe(32)
        if not server_token:
            logger.info("=" * 70)
            logger.info("Generated new authentication token for MCP server:")
            logger.info(f"  {self.server_token}")
            logger.info("=" * 70)
            logger.info("IMPORTANT: Save this token securely!")
            logger.info("Clients will need this token to connect to the server.")
            logger.info("=" * 70)

        # MCP server instance
        self.mcp_server: Optional[KimaiMCPServer] = None

    def verify_token(self, token: Optional[str]) -> bool:
        """Verify the authentication token.

        Args:
            token: Token to verify

        Returns:
            True if token is valid, False otherwise
        """
        if not token:
            return False
        return secrets.compare_digest(token, self.server_token)

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        """Lifespan context manager for FastAPI."""
        # Initialize MCP server
        self.mcp_server = KimaiMCPServer(
            base_url=self.kimai_url,
            api_token=self.kimai_token,
            default_user_id=self.kimai_user,
            ssl_verify=self.ssl_verify,
        )

        # Initialize client
        await self.mcp_server._ensure_client()

        # Verify connection
        try:
            version = await self.mcp_server.client.get_version()
            logger.info(f"Connected to Kimai {version.version}")
            logger.info(f"Remote MCP server ready on http://{self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to Kimai: {str(e)}")
            raise

        yield

        # Cleanup
        await self.mcp_server.cleanup()

    def create_app(self) -> FastAPI:
        """Create FastAPI application."""
        app = FastAPI(
            title="Kimai MCP Remote Server",
            description="Remote access to Kimai MCP server via HTTP/SSE",
            version=__version__,
            lifespan=self.lifespan,
        )

        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=self.allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @app.get("/health")
        async def health_check():
            """Health check endpoint."""
            return {
                "status": "healthy",
                "version": __version__,
                "kimai_url": self.kimai_url,
            }

        @app.get("/sse")
        async def handle_sse(
            request: Request,
            authorization: Optional[str] = Header(None),
        ):
            """Handle SSE connection for MCP."""
            # Verify authentication
            token = None
            if authorization:
                # Support both "Bearer TOKEN" and "TOKEN" formats
                if authorization.startswith("Bearer "):
                    token = authorization[7:]
                else:
                    token = authorization

            if not self.verify_token(token):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or missing authentication token",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Create SSE transport
            async with SseServerTransport("/messages") as transport:
                # Connect transport to MCP server
                await self.mcp_server.server.run(
                    transport.read_stream,
                    transport.write_stream,
                    self.mcp_server.server.create_initialization_options(),
                )

                # Stream events
                async def event_generator():
                    async for event in transport.sse():
                        yield event

                return StreamingResponse(
                    event_generator(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",  # Disable nginx buffering
                    },
                )

        @app.post("/messages")
        async def handle_messages(
            request: Request,
            authorization: Optional[str] = Header(None),
        ):
            """Handle incoming messages from client."""
            # Verify authentication
            token = None
            if authorization:
                if authorization.startswith("Bearer "):
                    token = authorization[7:]
                else:
                    token = authorization

            if not self.verify_token(token):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or missing authentication token",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Get message from request body
            try:
                message = await request.json()
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON")

            # Process message through MCP server
            # Note: This is a simplified implementation
            # In production, you'd need proper message routing
            return {"status": "received"}

        return app

    def run(self):
        """Run the remote MCP server."""
        app = self.create_app()
        uvicorn.run(
            app,
            host=self.host,
            port=self.port,
            log_level="info",
        )


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for remote server CLI."""
    parser = argparse.ArgumentParser(
        prog="kimai-mcp-server",
        description="Kimai MCP Remote Server - Centralized HTTP/SSE server for enterprise deployment",
        epilog="Documentation: https://github.com/glazperle/kimai_mcp",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Kimai connection settings
    parser.add_argument(
        "--kimai-url",
        metavar="URL",
        help="Kimai server URL (or set KIMAI_URL env var)",
    )
    parser.add_argument(
        "--kimai-token",
        metavar="TOKEN",
        help="Kimai API token (or set KIMAI_API_TOKEN env var)",
    )
    parser.add_argument(
        "--kimai-user",
        metavar="USER_ID",
        help="Default Kimai user ID (or set KIMAI_DEFAULT_USER env var)",
    )
    parser.add_argument(
        "--ssl-verify",
        metavar="VALUE",
        default="true",
        help="SSL verification for Kimai: 'true' (default), 'false', or path to CA cert",
    )

    # Server settings
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
        "--server-token",
        metavar="TOKEN",
        help="Authentication token for MCP server (or set MCP_SERVER_TOKEN env var, auto-generated if not set)",
    )
    parser.add_argument(
        "--allowed-origins",
        nargs="+",
        metavar="ORIGIN",
        help="Allowed CORS origins (default: all origins allowed)",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser


def main():
    """Main entry point for remote server."""
    parser = create_parser()
    args = parser.parse_args()

    # Load from environment if not provided
    kimai_url = args.kimai_url or os.getenv("KIMAI_URL")
    kimai_token = args.kimai_token or os.getenv("KIMAI_API_TOKEN")
    kimai_user = args.kimai_user or os.getenv("KIMAI_DEFAULT_USER")
    server_token = args.server_token or os.getenv("MCP_SERVER_TOKEN")

    # Validate required settings
    if not kimai_url:
        print("Error: Kimai URL is required (--kimai-url or KIMAI_URL env var)")
        return 1
    if not kimai_token:
        print("Error: Kimai API token is required (--kimai-token or KIMAI_API_TOKEN env var)")
        return 1

    # Parse SSL verify value
    ssl_verify: Optional[Union[bool, str]] = None
    if args.ssl_verify:
        ssl_value = args.ssl_verify.lower()
        if ssl_value == "true":
            ssl_verify = True
        elif ssl_value == "false":
            ssl_verify = False
        else:
            ssl_verify = args.ssl_verify

    # Create and run server
    server = RemoteMCPServer(
        kimai_url=kimai_url,
        kimai_token=kimai_token,
        kimai_user=kimai_user,
        ssl_verify=ssl_verify,
        server_token=server_token,
        host=args.host,
        port=args.port,
        allowed_origins=args.allowed_origins,
    )

    server.run()
    return 0


if __name__ == "__main__":
    exit(main())
