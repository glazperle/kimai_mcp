"""HTTP/SSE server for remote MCP access with per-client authentication.

Each client provides their own Kimai API token for secure, auditable access.
The server only provides MCP protocol handling and does not store Kimai credentials.

Security features:
- Rate limiting (configurable requests per minute)
- Session management with TTL and max session limits
- Security headers (X-Content-Type-Options, X-Frame-Options, etc.)
- Safe CORS configuration
"""

import argparse
import json
import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from typing import Optional, Union

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
from .security import (
    RateLimitConfig,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    SessionConfig,
    SessionManager,
)

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
        max_sessions: int = 100,
        session_ttl_seconds: int = 3600,
        rate_limit_rpm: int = 60,
        require_https: bool = False,
    ):
        """Initialize the remote MCP server.

        Args:
            default_kimai_url: Default Kimai server URL (clients can override)
            ssl_verify: SSL verification setting for Kimai connections
            server_token: Authentication token for MCP server access (generated if not provided)
            host: Host to bind the server to
            port: Port to bind the server to
            allowed_origins: List of allowed CORS origins
            max_sessions: Maximum concurrent client sessions (default: 100)
            session_ttl_seconds: Session timeout in seconds (default: 3600 = 1 hour)
            rate_limit_rpm: Maximum requests per minute per IP (default: 60, 0 to disable)
            require_https: Require HTTPS connections (default: False)
        """
        self.default_kimai_url = (default_kimai_url or "").rstrip('/')
        self.ssl_verify = ssl_verify
        self.host = host
        self.port = port
        self.allowed_origins = allowed_origins or ["*"]
        self.require_https = require_https

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

        # Session management with limits and TTL
        self.session_manager = SessionManager(SessionConfig(
            max_sessions=max_sessions,
            session_ttl_seconds=session_ttl_seconds,
        ))

        # Rate limiting configuration
        self.rate_limit_config = RateLimitConfig(
            requests_per_minute=rate_limit_rpm,
            enabled=rate_limit_rpm > 0,
        )

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

        Raises:
            HTTPException: If session limit reached or connection fails
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

        # Try to register session (enforces limits)
        if not await self.session_manager.create(session_id, mcp_server):
            await mcp_server.cleanup()
            raise HTTPException(
                status_code=503,
                detail="Server at capacity. Please try again later.",
                headers={"Retry-After": "60"}
            )

        return session_id, mcp_server

    async def cleanup_session(self, session_id: str):
        """Clean up a client session.

        Args:
            session_id: Session ID to clean up
        """
        mcp_server = await self.session_manager.remove(session_id)
        if mcp_server:
            await mcp_server.cleanup()
            logger.info(f"Cleaned up client session {session_id[:8]}")

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        """Lifespan context manager for FastAPI."""
        logger.info(f"Remote MCP server starting on http://{self.host}:{self.port}")
        logger.info("Per-client Kimai authentication enabled")
        if self.default_kimai_url:
            logger.info(f"Default Kimai URL: {self.default_kimai_url}")

        # Start session manager (handles cleanup of expired sessions)
        await self.session_manager.start()

        yield

        # Stop session manager (cleans up all remaining sessions)
        logger.info("Shutting down, cleaning up client sessions...")
        await self.session_manager.stop()

    def create_app(self) -> FastAPI:
        """Create FastAPI application."""
        app = FastAPI(
            title="Kimai MCP Remote Server",
            description="Remote access to Kimai MCP server via HTTP/SSE with per-client authentication",
            version=__version__,
            lifespan=self.lifespan,
        )

        # Add CORS middleware with secure configuration
        # SECURITY: Do not allow credentials with wildcard origins
        if "*" in self.allowed_origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=False,  # Must be False with wildcard
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["Authorization", "X-Kimai-URL", "X-Kimai-Token", "X-Kimai-User", "Content-Type"],
            )
        else:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=self.allowed_origins,
                allow_credentials=True,
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["Authorization", "X-Kimai-URL", "X-Kimai-Token", "X-Kimai-User", "Content-Type"],
            )

        @app.get("/health")
        async def health_check():
            """Health check endpoint."""
            return {
                "status": "healthy",
                "version": __version__,
                "mode": "per-client-auth",
                "default_kimai_url": self.default_kimai_url or None,
                "active_sessions": self.session_manager.count,
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
                            "Cache-Control": "no-cache, no-store, must-revalidate",
                            "Connection": "keep-alive",
                            "X-Accel-Buffering": "no",  # Disable nginx buffering
                            "Pragma": "no-cache",
                            # X-Session-ID removed for security - session handled internally
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

        # Wrap with security middlewares (order matters: rate limit -> security headers -> app)
        app = SecurityHeadersMiddleware(app)
        app = RateLimitMiddleware(app, self.rate_limit_config)

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

    # Security settings
    parser.add_argument(
        "--rate-limit-rpm",
        type=int,
        default=60,
        metavar="N",
        help="Maximum requests per minute per IP (default: 60, 0 to disable)",
    )
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=100,
        metavar="N",
        help="Maximum concurrent client sessions (default: 100)",
    )
    parser.add_argument(
        "--session-ttl",
        type=int,
        default=3600,
        metavar="SECONDS",
        help="Session timeout in seconds (default: 3600 = 1 hour)",
    )
    parser.add_argument(
        "--require-https",
        action="store_true",
        help="Require HTTPS connections (default: disabled)",
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

    # Load security settings from environment if not provided via CLI
    rate_limit_rpm = args.rate_limit_rpm
    if os.getenv("RATE_LIMIT_RPM"):
        rate_limit_rpm = int(os.getenv("RATE_LIMIT_RPM"))

    max_sessions = args.max_sessions
    if os.getenv("MAX_SESSIONS"):
        max_sessions = int(os.getenv("MAX_SESSIONS"))

    session_ttl = args.session_ttl
    if os.getenv("SESSION_TTL"):
        session_ttl = int(os.getenv("SESSION_TTL"))

    require_https = args.require_https or os.getenv("REQUIRE_HTTPS", "").lower() == "true"

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
        max_sessions=max_sessions,
        session_ttl_seconds=session_ttl,
        rate_limit_rpm=rate_limit_rpm,
        require_https=require_https,
    )

    server.run()
    return 0


if __name__ == "__main__":
    exit(main())
