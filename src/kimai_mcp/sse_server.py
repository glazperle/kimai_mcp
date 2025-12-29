"""HTTP/SSE server for remote MCP access with per-client authentication.

Each client provides their own Kimai API token for secure, auditable access.
The server only provides MCP protocol handling and does not store Kimai credentials.
"""

import argparse
import json
import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Optional, Union

try:
    import uvicorn
    from fastapi import FastAPI, Header, HTTPException, Request
    from fastapi.responses import StreamingResponse
    from starlette.middleware.cors import CORSMiddleware
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
    """Remote MCP server with per-client Kimai authentication.

    Each client provides their own Kimai URL and API token, ensuring:
    - Individual user permissions and access control
    - Auditable actions per user
    - No shared credentials
    - Enhanced security and compliance
    """

    def __init__(
        self,
        default_kimai_url: Optional[str] = None,
        ssl_verify: Optional[Union[bool, str]] = None,
        server_token: Optional[str] = None,
        host: str = "0.0.0.0",
        port: int = 8000,
        allowed_origins: Optional[list[str]] = None,
    ):
        """Initialize the remote MCP server.

        Args:
            default_kimai_url: Default Kimai server URL (clients can override)
            ssl_verify: SSL verification setting for Kimai connections
            server_token: Authentication token for MCP server access (generated if not provided)
            host: Host to bind the server to
            port: Port to bind the server to
            allowed_origins: List of allowed CORS origins
        """
        self.default_kimai_url = (default_kimai_url or "").rstrip('/')
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

        # Active client sessions (connection_id -> KimaiMCPServer)
        self.client_sessions: Dict[str, KimaiMCPServer] = {}

    def verify_token(self, token: Optional[str]) -> bool:
        """Verify the MCP server authentication token.

        Args:
            token: Token to verify

        Returns:
            True if token is valid, False otherwise
        """
        if not token:
            return False
        return secrets.compare_digest(token, self.server_token)

    def extract_kimai_credentials(
        self,
        x_kimai_url: Optional[str] = None,
        x_kimai_token: Optional[str] = None
    ) -> tuple[str, str]:
        """Extract and validate Kimai credentials from request headers.

        Args:
            x_kimai_url: Kimai URL from X-Kimai-URL header
            x_kimai_token: Kimai API token from X-Kimai-Token header

        Returns:
            Tuple of (kimai_url, kimai_token)

        Raises:
            HTTPException: If credentials are missing or invalid
        """
        # Use client-provided URL or default
        kimai_url = (x_kimai_url or self.default_kimai_url or "").rstrip('/')

        if not kimai_url:
            raise HTTPException(
                status_code=400,
                detail="Kimai URL is required. Provide via X-Kimai-URL header or server default."
            )

        if not x_kimai_token:
            raise HTTPException(
                status_code=400,
                detail="Kimai API token is required. Provide via X-Kimai-Token header."
            )

        return kimai_url, x_kimai_token

    async def create_client_session(
        self,
        kimai_url: str,
        kimai_token: str,
        user_id: Optional[str] = None
    ) -> tuple[str, KimaiMCPServer]:
        """Create a new MCP server instance for a client.

        Args:
            kimai_url: Kimai server URL
            kimai_token: Kimai API token
            user_id: Optional user identifier for logging

        Returns:
            Tuple of (session_id, mcp_server)
        """
        session_id = str(uuid.uuid4())

        # Create MCP server instance for this client
        mcp_server = KimaiMCPServer(
            base_url=kimai_url,
            api_token=kimai_token,
            default_user_id=user_id,
            ssl_verify=self.ssl_verify,
        )

        # Initialize client
        await mcp_server._ensure_client()

        # Verify connection
        try:
            version = await mcp_server.client.get_version()
            logger.info(
                f"Client session {session_id[:8]} connected to Kimai {version.version} "
                f"at {kimai_url}"
            )
        except Exception as e:
            logger.error(f"Failed to connect to Kimai for session {session_id[:8]}: {str(e)}")
            await mcp_server.cleanup()
            raise HTTPException(
                status_code=502,
                detail=f"Failed to connect to Kimai: {str(e)}"
            )

        # Store session
        self.client_sessions[session_id] = mcp_server

        return session_id, mcp_server

    async def cleanup_session(self, session_id: str):
        """Clean up a client session.

        Args:
            session_id: Session ID to clean up
        """
        if session_id in self.client_sessions:
            mcp_server = self.client_sessions[session_id]
            await mcp_server.cleanup()
            del self.client_sessions[session_id]
            logger.info(f"Cleaned up client session {session_id[:8]}")

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        """Lifespan context manager for FastAPI."""
        logger.info(f"Remote MCP server starting on http://{self.host}:{self.port}")
        logger.info("Per-client Kimai authentication enabled")
        if self.default_kimai_url:
            logger.info(f"Default Kimai URL: {self.default_kimai_url}")

        yield

        # Cleanup all client sessions
        logger.info("Shutting down, cleaning up client sessions...")
        for session_id in list(self.client_sessions.keys()):
            await self.cleanup_session(session_id)

    def create_app(self) -> FastAPI:
        """Create FastAPI application."""
        app = FastAPI(
            title="Kimai MCP Remote Server",
            description="Remote access to Kimai MCP server via HTTP/SSE with per-client authentication",
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
                "mode": "per-client-auth",
                "default_kimai_url": self.default_kimai_url or None,
                "active_sessions": len(self.client_sessions),
            }

        @app.get("/sse")
        async def handle_sse(
            request: Request,
            authorization: Optional[str] = Header(None),
            x_kimai_url: Optional[str] = Header(None, alias="X-Kimai-URL"),
            x_kimai_token: Optional[str] = Header(None, alias="X-Kimai-Token"),
            x_kimai_user: Optional[str] = Header(None, alias="X-Kimai-User"),
        ):
            """Handle SSE connection for MCP with per-client Kimai credentials.

            Required Headers:
                Authorization: Bearer <MCP_SERVER_TOKEN>
                X-Kimai-Token: <USER_KIMAI_API_TOKEN>

            Optional Headers:
                X-Kimai-URL: <KIMAI_SERVER_URL> (uses server default if not provided)
                X-Kimai-User: <DEFAULT_USER_ID>
            """
            # Verify MCP server authentication
            token = None
            if authorization:
                if authorization.startswith("Bearer "):
                    token = authorization[7:]
                else:
                    token = authorization

            if not self.verify_token(token):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or missing MCP server authentication token",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Extract and validate Kimai credentials
            kimai_url, kimai_token = self.extract_kimai_credentials(
                x_kimai_url, x_kimai_token
            )

            # Create client session
            session_id, mcp_server = await self.create_client_session(
                kimai_url, kimai_token, x_kimai_user
            )

            try:
                # Create SSE transport
                async with SseServerTransport("/messages") as transport:
                    # Connect transport to MCP server
                    await mcp_server.server.run(
                        transport.read_stream,
                        transport.write_stream,
                        mcp_server.server.create_initialization_options(),
                    )

                    # Stream events
                    async def event_generator():
                        try:
                            async for event in transport.sse():
                                yield event
                        finally:
                            # Cleanup session when connection closes
                            await self.cleanup_session(session_id)

                    return StreamingResponse(
                        event_generator(),
                        media_type="text/event-stream",
                        headers={
                            "Cache-Control": "no-cache",
                            "Connection": "keep-alive",
                            "X-Accel-Buffering": "no",  # Disable nginx buffering
                            "X-Session-ID": session_id,
                        },
                    )
            except Exception:
                # Cleanup on error
                await self.cleanup_session(session_id)
                raise

        @app.post("/messages")
        async def handle_messages(
            request: Request,
            authorization: Optional[str] = Header(None),
            x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
        ):
            """Handle incoming messages from client.

            This endpoint is used by the SSE transport for client-to-server messages.
            """
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
                _ = await request.json()
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON")

            # Note: Message handling is done via the SSE transport
            # This endpoint acknowledges receipt
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
        description="Kimai MCP Remote Server - Centralized HTTP/SSE server with per-client authentication",
        epilog="Documentation: https://github.com/glazperle/kimai_mcp",
        formatter_class=argparse.RawDescriptionHelpFormatter,
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

    # Optional Kimai settings
    parser.add_argument(
        "--default-kimai-url",
        metavar="URL",
        help="Default Kimai server URL (clients can override, or set DEFAULT_KIMAI_URL env var)",
    )
    parser.add_argument(
        "--ssl-verify",
        metavar="VALUE",
        default="true",
        help="SSL verification for Kimai: 'true' (default), 'false', or path to CA cert",
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
    default_kimai_url = args.default_kimai_url or os.getenv("DEFAULT_KIMAI_URL")
    server_token = args.server_token or os.getenv("MCP_SERVER_TOKEN")

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
        default_kimai_url=default_kimai_url,
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
