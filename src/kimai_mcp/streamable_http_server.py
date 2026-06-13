"""Streamable HTTP server for Claude.ai Connectors with multi-user support.

This server implements the MCP Streamable HTTP transport specification,
allowing it to work as a remote MCP server with Claude.ai Connectors.

Authentication (v2.12+):
- OAuth 2.1 (recommended): single protected endpoint /mcp. Clients register
  via Dynamic Client Registration, users authenticate with their user slug
  and per-user auth_secret on an HTML login form (PKCE S256 mandatory).
- Legacy (deprecated): per-user endpoints /mcp/{user_slug} with secret slugs.
  Can be disabled with --disable-legacy-slugs.

Security features:
- Rate limiting (configurable requests per minute)
- Enumeration protection with random delays
- Security headers
- Proxy headers (X-Forwarded-For) only honored from trusted proxies
"""

import argparse
import asyncio
import contextlib
import logging
import os
import re
from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional

from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server import Server
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.server.auth.routes import (
    build_resource_metadata_url,
    create_auth_routes,
    create_protected_resource_routes,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool, TextContent

from .client import KimaiClient, KimaiAPIError
from .oauth import KimaiOAuthProvider
from .oidc import OIDCConfig
from .server import __version__, format_api_error
from .user_config import UsersConfig, UserConfig
from .security import (
    EnumerationProtection,
    RateLimitConfig,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    get_client_ip,
    random_delay,
)

# Shared tool registry (single source of truth for both servers)
from .tools.registry import all_tools, dispatch_tool

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Interval for the periodic security cleanup task (seconds)
SECURITY_CLEANUP_INTERVAL_SECONDS = 300


def is_low_entropy_slug(slug: str) -> bool:
    """Heuristic for guessable legacy user slugs.

    A slug is considered low-entropy if it is shorter than 16 characters
    or consists only of a lowercase word (e.g. a first name).
    """
    if len(slug) < 16:
        return True
    if slug.isalpha() and slug.islower():
        return True
    return False


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
        return all_tools()

    async def _call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
        """Handle tool calls."""
        if self.kimai_client is None:
            return [TextContent(type="text", text="Error: Kimai client not initialized")]

        arguments = arguments or {}

        try:
            return await dispatch_tool(self.kimai_client, name, arguments)

        except KimaiAPIError as e:
            logger.error(
                f"Kimai API Error for user '{self.user_slug}' in tool {name}: "
                f"{e.message} (Status: {e.status_code}), Details: {e.details}"
            )
            # Use the shared formatter so stdio and remote transports stay identical
            return [TextContent(type="text", text=format_api_error(e))]
        except Exception as e:
            logger.error(f"Error for user '{self.user_slug}' calling tool {name}: {e}", exc_info=True)
            return [TextContent(type="text", text=f"Error: {str(e)}")]


class MCPRoutingMiddleware:
    """ASGI middleware that routes MCP endpoints to the appropriate session manager.

    Routes:
    - /mcp: OAuth-protected endpoint. Delegated to the bearer-auth wrapped app,
      which maps the verified token's subject (user slug) to the session.
    - /mcp/{user_slug}: legacy (deprecated) per-user endpoint, optionally disabled.

    The StreamableHTTPSessionManager requires direct ASGI access (scope, receive,
    send), so we intercept MCP requests before they reach Starlette's router.

    Security features:
    - Random delay on 404 to prevent timing-based enumeration attacks
    - Enumeration protection to block clients with excessive 404s
    - Proxy headers only honored from trusted proxies
    """

    # Pattern to match /mcp/{user_slug} paths
    MCP_PATH_PATTERN = re.compile(r"^/mcp/([a-zA-Z0-9_-]+)$")

    def __init__(
        self,
        app: ASGIApp,
        user_sessions: Dict[str, UserMCPSession],
        oauth_mcp_app: Optional[ASGIApp] = None,
        legacy_slugs_enabled: bool = True,
        trusted_proxies: Optional[List[str]] = None,
    ):
        """Initialize middleware.

        Args:
            app: The wrapped ASGI application (Starlette)
            user_sessions: Dictionary of user slug to session
            oauth_mcp_app: Bearer-auth protected ASGI app serving /mcp
            legacy_slugs_enabled: Whether the deprecated /mcp/{slug} routes are served
            trusted_proxies: IPs of reverse proxies whose forwarding headers may be trusted
        """
        self.app = app
        self.user_sessions = user_sessions
        self.oauth_mcp_app = oauth_mcp_app
        self.legacy_slugs_enabled = legacy_slugs_enabled
        self.trusted_proxies = trusted_proxies or []
        # Enumeration protection: block clients with excessive 404s
        self.enumeration_protection = EnumerationProtection(
            max_404_per_minute=10,
            block_duration_seconds=300,
        )

    def _get_client_ip(self, scope: Scope) -> str:
        """Extract client IP from ASGI scope (proxy headers only from trusted proxies)."""
        return get_client_ip(scope, self.trusted_proxies)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle ASGI request."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # OAuth-protected endpoint (token-based user mapping)
        if path == "/mcp" and self.oauth_mcp_app is not None:
            await self.oauth_mcp_app(scope, receive, send)
            return

        match = self.MCP_PATH_PATTERN.match(path)
        if match:
            if not self.legacy_slugs_enabled:
                response = JSONResponse({"error": "Not found"}, status_code=404)
                await response(scope, receive, send)
                return
            user_slug = match.group(1)
            await self._handle_mcp_request(scope, receive, send, user_slug)
        else:
            # Pass through to Starlette for other routes
            await self.app(scope, receive, send)

    async def _handle_mcp_request(
        self, scope: Scope, receive: Receive, send: Send, user_slug: str
    ) -> None:
        """Handle MCP request for a specific user (legacy slug routing)."""
        client_ip = self._get_client_ip(scope)

        # Check if client is blocked due to enumeration attempts
        if await self.enumeration_protection.is_blocked(client_ip):
            response = JSONResponse(
                {"error": "Too many failed requests"},
                status_code=429,
                headers={"Retry-After": "300"},
            )
            await response(scope, receive, send)
            return

        if user_slug not in self.user_sessions:
            # Add random delay to prevent timing-based enumeration
            await random_delay(0.1, 0.3)

            # Record 404 and potentially block client
            await self.enumeration_protection.record_404(client_ip)

            # Generic error message (don't reveal whether slug format is valid)
            response = JSONResponse(
                {"error": "Not found"},
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
        rate_limit_rpm: int = 60,
        public_url: Optional[str] = None,
        trusted_proxies: Optional[List[str]] = None,
        disable_legacy_slugs: bool = False,
        oauth_state_file: Optional[str] = None,
        oidc_config: Optional[OIDCConfig] = None,
    ):
        """Initialize the server.

        Args:
            users_config: Configuration for all users
            host: Host to bind to
            port: Port to bind to
            rate_limit_rpm: Maximum requests per minute per IP (default: 60, 0 to disable)
            public_url: Public base URL of this server, used as OAuth issuer and
                resource URL (required behind a reverse proxy). Defaults to
                http://localhost:{port}.
            trusted_proxies: IPs of reverse proxies whose X-Forwarded-For /
                X-Real-IP headers may be trusted.
            disable_legacy_slugs: Disable the deprecated /mcp/{user_slug} routes.
            oauth_state_file: Optional JSON file to persist registered OAuth clients.
            oidc_config: Optional OIDC relying-party config. When set, the OAuth
                login step federates to an external OIDC provider instead of the
                built-in slug + auth_secret form.
        """
        self.users_config = users_config
        self.host = host
        self.port = port
        self.user_sessions: Dict[str, UserMCPSession] = {}
        # Serializes on-demand (re)initialization of sessions for configured users
        # whose startup init failed (e.g. Kimai was briefly unreachable).
        self._session_init_lock = asyncio.Lock()
        self.trusted_proxies = list(trusted_proxies) if trusted_proxies else []
        self.legacy_slugs_enabled = not disable_legacy_slugs

        self.public_url = (public_url or f"http://localhost:{port}").rstrip("/")

        # OAuth 2.1 authorization server settings (SDK scaffolding)
        self.auth_settings = AuthSettings(
            issuer_url=AnyHttpUrl(self.public_url),
            resource_server_url=AnyHttpUrl(f"{self.public_url}/mcp"),
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
            required_scopes=None,
        )
        self.oauth_provider = KimaiOAuthProvider(
            users_config=users_config,
            public_url=self.public_url,
            state_file=oauth_state_file,
            oidc_config=oidc_config,
        )

        # Rate limiting configuration
        self.rate_limit_config = RateLimitConfig(
            requests_per_minute=rate_limit_rpm,
            enabled=rate_limit_rpm > 0,
        )

        # References for the periodic security cleanup task
        self._rate_limit_middleware: Optional[RateLimitMiddleware] = None
        self._routing_middleware: Optional[MCPRoutingMiddleware] = None

    async def initialize_users(self) -> None:
        """Initialize all user sessions."""
        for slug, config in self.users_config.users.items():
            session = UserMCPSession(slug, config)
            try:
                await session.initialize()
            except Exception as e:
                logger.error(f"Failed to initialize user '{slug}': {e}")
                # Release resources (e.g. the httpx client) of the failed session
                with contextlib.suppress(Exception):
                    await session.cleanup()
                # Continue with other users
                continue
            self.user_sessions[slug] = session
            logger.info(f"Initialized session for user '{slug}'")

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

    def _warn_low_entropy_slugs(self) -> None:
        """Warn about guessable legacy slugs at startup."""
        if not self.legacy_slugs_enabled:
            return
        for slug in self.users_config.users:
            if is_low_entropy_slug(slug):
                logger.warning(
                    f"User slug '{slug}' has low entropy (shorter than 16 characters or a "
                    f"plain lowercase word) and is exposed at the deprecated legacy endpoint "
                    f"/mcp/{slug}. Anyone who guesses this slug gains full access to the "
                    f"associated Kimai account. Please switch to the OAuth-protected /mcp "
                    f"endpoint (set 'auth_secret' for the user) and start the server with "
                    f"--disable-legacy-slugs."
                )

    async def _security_cleanup_loop(self) -> None:
        """Periodically clean up rate limiter, enumeration protection and OAuth state."""
        while True:
            await asyncio.sleep(SECURITY_CLEANUP_INTERVAL_SECONDS)
            try:
                if self._rate_limit_middleware is not None:
                    await self._rate_limit_middleware.limiter.cleanup_old_entries()
                if self._routing_middleware is not None:
                    await self._routing_middleware.enumeration_protection.cleanup_old_entries()
                self.oauth_provider.cleanup_expired()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error in security cleanup task: {e}")

    @contextlib.asynccontextmanager
    async def lifespan(self, app: Starlette) -> AsyncIterator[None]:
        """Manage server lifecycle."""
        logger.info(f"Starting Streamable HTTP MCP server on {self.host}:{self.port}")
        logger.info(f"Version: {__version__}")
        logger.info(f"Public URL (OAuth issuer): {self.public_url}")

        # Initialize users
        await self.initialize_users()
        self._warn_low_entropy_slugs()

        # Periodic security cleanup (rate limiter / enumeration protection / OAuth)
        cleanup_task = asyncio.create_task(self._security_cleanup_loop())

        try:
            # Start all session managers
            async with contextlib.AsyncExitStack() as stack:
                for slug, session in self.user_sessions.items():
                    if session.session_manager:
                        await stack.enter_async_context(session.session_manager.run())
                        logger.info(f"Started session manager for user '{slug}'")

                logger.info(f"Server ready with {len(self.user_sessions)} user session(s)")
                logger.info(f"OAuth-protected MCP endpoint: {self.public_url}/mcp")
                if self.legacy_slugs_enabled:
                    logger.warning(
                        "Legacy slug endpoints /mcp/{user_slug} are enabled (DEPRECATED). "
                        "Use the OAuth endpoint /mcp and --disable-legacy-slugs instead."
                    )
                else:
                    logger.info("Legacy slug endpoints are disabled")

                yield
        finally:
            # Cleanup
            logger.info("Shutting down...")
            cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cleanup_task
            await self.cleanup_users()
            with contextlib.suppress(Exception):
                await self.oauth_provider.aclose()

    async def health_check(self, request: Request) -> JSONResponse:
        """Health check endpoint.

        Note: User slugs are not exposed for security (prevents enumeration).
        """
        return JSONResponse({
            "status": "healthy",
            "version": __version__,
            "transport": "streamable-http",
            "user_count": len(self.user_sessions),  # Only count, not slugs
        })

    async def root(self, request: Request) -> JSONResponse:
        """Root endpoint with server info."""
        return JSONResponse({
            "name": "Kimai MCP Server",
            "version": __version__,
            "transport": "streamable-http",
            "endpoints": {
                "health": f"{self.public_url}/health",
                "mcp": f"{self.public_url}/mcp",
                "oauth_metadata": f"{self.public_url}/.well-known/oauth-authorization-server",
            },
            "documentation": "https://github.com/glazperle/kimai_mcp",
        })

    async def _ensure_session(self, slug: Optional[str]) -> Optional["UserMCPSession"]:
        """Return an active session for the slug, initializing it on demand.

        Sessions whose startup init failed (e.g. Kimai temporarily unreachable)
        are not kept in user_sessions; a configured user would otherwise stay in a
        permanent 403 loop until the next restart. This retries the init once per
        request under a lock so an outage at boot self-heals.
        """
        if not slug:
            return None
        session = self.user_sessions.get(slug)
        if session is not None and session.session_manager is not None:
            return session
        if slug not in self.users_config.users:
            return None
        async with self._session_init_lock:
            # Re-check after acquiring the lock (another request may have won).
            session = self.user_sessions.get(slug)
            if session is not None and session.session_manager is not None:
                return session
            new_session = UserMCPSession(slug, self.users_config.users[slug])
            try:
                await new_session.initialize()
            except Exception as e:
                logger.error(f"On-demand initialization failed for user '{slug}': {e}")
                with contextlib.suppress(Exception):
                    await new_session.cleanup()
                return None
            self.user_sessions[slug] = new_session
            logger.info(f"On-demand initialized session for user '{slug}'")
            return new_session

    async def _handle_oauth_mcp_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve /mcp for an authenticated user (token subject -> session)."""
        user = scope.get("user")
        access_token = getattr(user, "access_token", None)
        subject = getattr(access_token, "subject", None)

        session = await self._ensure_session(subject)
        if session is None or session.session_manager is None:
            response = JSONResponse(
                {"error": "No active session for the authenticated user"},
                status_code=503,
            )
            await response(scope, receive, send)
            return

        await session.session_manager.handle_request(scope, receive, send)

    def _create_oauth_mcp_app(self) -> ASGIApp:
        """Build the bearer-auth protected ASGI app for the /mcp endpoint."""
        resource_metadata_url = build_resource_metadata_url(self.auth_settings.resource_server_url)
        return AuthenticationMiddleware(
            app=RequireAuthMiddleware(
                self._handle_oauth_mcp_request,
                required_scopes=self.auth_settings.required_scopes or [],
                resource_metadata_url=resource_metadata_url,
            ),
            backend=BearerAuthBackend(ProviderTokenVerifier(self.oauth_provider)),
        )

    def create_app(self) -> ASGIApp:
        """Create the ASGI application with OAuth, MCP routing and security middlewares."""
        routes = [
            Route("/", endpoint=self.root, methods=["GET"]),
            Route("/health", endpoint=self.health_check, methods=["GET"]),
        ]

        # OAuth 2.1 authorization server routes (RFC 8414 metadata, /authorize,
        # /token, /register, /revoke) provided by the MCP SDK scaffolding.
        routes.extend(
            create_auth_routes(
                provider=self.oauth_provider,
                issuer_url=self.auth_settings.issuer_url,
                service_documentation_url=None,
                client_registration_options=self.auth_settings.client_registration_options,
                revocation_options=self.auth_settings.revocation_options,
            )
        )

        # RFC 9728 protected resource metadata for /mcp
        routes.extend(
            create_protected_resource_routes(
                resource_url=self.auth_settings.resource_server_url,
                authorization_servers=[self.auth_settings.issuer_url],
                resource_name="Kimai MCP Server",
            )
        )

        # HTML login form for the authorization flow
        routes.extend(self.oauth_provider.routes())

        starlette_app = Starlette(
            routes=routes,
            lifespan=self.lifespan,
        )

        # Wrap with MCP routing middleware (handles /mcp and legacy /mcp/{slug})
        self._routing_middleware = MCPRoutingMiddleware(
            starlette_app,
            self.user_sessions,
            oauth_mcp_app=self._create_oauth_mcp_app(),
            legacy_slugs_enabled=self.legacy_slugs_enabled,
            trusted_proxies=self.trusted_proxies,
        )

        # Security middlewares (order matters: rate limit -> security headers -> app)
        app: ASGIApp = SecurityHeadersMiddleware(self._routing_middleware)
        self._rate_limit_middleware = RateLimitMiddleware(
            app, self.rate_limit_config, trusted_proxies=self.trusted_proxies
        )
        return self._rate_limit_middleware

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
        "--public-url",
        metavar="URL",
        help=(
            "Public base URL of this server, used as OAuth issuer/resource URL "
            "(required behind a reverse proxy; or set KIMAI_MCP_PUBLIC_URL env var). "
            "Default: http://localhost:{port}"
        ),
    )
    parser.add_argument(
        "--oauth-state-file",
        metavar="FILE",
        help=(
            "Optional JSON file to persist registered OAuth clients across restarts "
            "(or set KIMAI_MCP_OAUTH_STATE_FILE env var)"
        ),
    )
    parser.add_argument(
        "--disable-legacy-slugs",
        action="store_true",
        help=(
            "Disable the deprecated /mcp/{user_slug} endpoints; only the "
            "OAuth-protected /mcp endpoint remains "
            "(or set KIMAI_MCP_DISABLE_LEGACY_SLUGS=true)"
        ),
    )

    # OIDC federated login backend (optional; default is the built-in slug login)
    parser.add_argument(
        "--auth-backend",
        choices=["local", "oidc"],
        default=None,
        help=(
            "Login backend: 'local' (built-in slug + auth_secret form, default) or "
            "'oidc' (federate to an external OIDC provider). "
            "Or set KIMAI_MCP_AUTH_BACKEND."
        ),
    )
    parser.add_argument(
        "--oidc-issuer",
        metavar="URL",
        help="OIDC issuer URL (required for --auth-backend oidc; or KIMAI_MCP_OIDC_ISSUER)",
    )
    parser.add_argument(
        "--oidc-client-id",
        metavar="ID",
        help="OIDC client ID (required for --auth-backend oidc; or KIMAI_MCP_OIDC_CLIENT_ID)",
    )
    parser.add_argument(
        "--oidc-client-secret",
        metavar="SECRET",
        help=(
            "OIDC client secret for confidential clients (optional; public/PKCE-only if omitted). "
            "Prefer the KIMAI_MCP_OIDC_CLIENT_SECRET env var over the CLI flag."
        ),
    )
    parser.add_argument(
        "--oidc-scopes",
        metavar="SCOPES",
        help="OIDC scopes, space- or comma-separated (default: 'openid email profile'; or KIMAI_MCP_OIDC_SCOPES)",
    )
    parser.add_argument(
        "--oidc-identity-claim",
        metavar="CLAIM",
        help=(
            "id_token claim used to map to a user's oidc_identity (default: email; "
            "or KIMAI_MCP_OIDC_IDENTITY_CLAIM)"
        ),
    )
    parser.add_argument(
        "--oidc-discovery-url",
        metavar="URL",
        help="Override the OIDC discovery URL (default: <issuer>/.well-known/openid-configuration)",
    )
    parser.add_argument(
        "--oidc-allow-unverified-email",
        action="store_true",
        help=(
            "Accept the OIDC 'email' claim even when 'email_verified' is not true. "
            "Only enable for providers that do not emit email_verified but are trusted "
            "to assert verified emails (or set KIMAI_MCP_OIDC_ALLOW_UNVERIFIED_EMAIL=true)"
        ),
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
        "--trusted-proxy",
        action="append",
        default=None,
        metavar="IP",
        dest="trusted_proxies",
        help=(
            "IP of a trusted reverse proxy whose X-Forwarded-For/X-Real-IP headers "
            "are honored; may be given multiple times "
            "(or set KIMAI_MCP_TRUSTED_PROXIES as comma-separated list). "
            "Without trusted proxies these headers are ignored."
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser


def _build_oidc_config(args: argparse.Namespace) -> Optional[OIDCConfig]:
    """Build an OIDCConfig from CLI/env if the oidc backend is selected, else None.

    Raises ValueError on a misconfigured oidc backend (handled by main()).
    """
    backend = (args.auth_backend or os.getenv("KIMAI_MCP_AUTH_BACKEND") or "local").lower()
    if backend != "oidc":
        return None

    issuer = args.oidc_issuer or os.getenv("KIMAI_MCP_OIDC_ISSUER")
    client_id = args.oidc_client_id or os.getenv("KIMAI_MCP_OIDC_CLIENT_ID")
    missing = [
        name for name, val in (("--oidc-issuer", issuer), ("--oidc-client-id", client_id)) if not val
    ]
    if missing:
        raise ValueError(
            f"--auth-backend oidc requires {', '.join(missing)} "
            f"(or the corresponding KIMAI_MCP_OIDC_* environment variables)"
        )

    client_secret = args.oidc_client_secret or os.getenv("KIMAI_MCP_OIDC_CLIENT_SECRET")
    discovery_url = args.oidc_discovery_url or os.getenv("KIMAI_MCP_OIDC_DISCOVERY_URL")
    identity_claim = args.oidc_identity_claim or os.getenv("KIMAI_MCP_OIDC_IDENTITY_CLAIM")
    scopes_raw = args.oidc_scopes or os.getenv("KIMAI_MCP_OIDC_SCOPES")

    allow_unverified_email = args.oidc_allow_unverified_email or (
        os.getenv("KIMAI_MCP_OIDC_ALLOW_UNVERIFIED_EMAIL", "").lower() in ("1", "true", "yes")
    )

    kwargs: Dict[str, object] = {"issuer": issuer, "client_id": client_id}
    if client_secret:
        kwargs["client_secret"] = client_secret
    if discovery_url:
        kwargs["discovery_url"] = discovery_url
    if scopes_raw:
        scopes = [s for s in re.split(r"[,\s]+", scopes_raw.strip()) if s]
        if scopes:
            kwargs["scopes"] = scopes
    if identity_claim:
        # The configured claim leads OIDCConfig's default fallback list.
        default_claims = OIDCConfig.model_fields["identity_claims"].default_factory()
        fallbacks = [c for c in default_claims if c != identity_claim]
        kwargs["identity_claims"] = [identity_claim, *fallbacks]
    if allow_unverified_email:
        kwargs["require_verified_email"] = False

    logger.info(f"OIDC auth backend enabled (issuer: {issuer})")
    return OIDCConfig(**kwargs)


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

    # Load security settings from environment if not provided via CLI
    rate_limit_rpm = args.rate_limit_rpm
    if os.getenv("RATE_LIMIT_RPM"):
        rate_limit_rpm = int(os.getenv("RATE_LIMIT_RPM"))

    public_url = args.public_url or os.getenv("KIMAI_MCP_PUBLIC_URL")
    oauth_state_file = args.oauth_state_file or os.getenv("KIMAI_MCP_OAUTH_STATE_FILE")

    trusted_proxies = list(args.trusted_proxies or [])
    env_proxies = os.getenv("KIMAI_MCP_TRUSTED_PROXIES")
    if env_proxies:
        trusted_proxies.extend(p.strip() for p in env_proxies.split(",") if p.strip())

    disable_legacy_slugs = args.disable_legacy_slugs or (
        os.getenv("KIMAI_MCP_DISABLE_LEGACY_SLUGS", "").lower() in ("1", "true", "yes")
    )

    try:
        oidc_config = _build_oidc_config(args)

        # Load users config
        users_config = UsersConfig.load(args.users_config)
        logger.info(f"Loaded configuration for {len(users_config.users)} user(s)")

        # Create and run server
        server = StreamableHTTPMCPServer(
            users_config=users_config,
            host=args.host,
            port=args.port,
            rate_limit_rpm=rate_limit_rpm,
            public_url=public_url,
            trusted_proxies=trusted_proxies,
            disable_legacy_slugs=disable_legacy_slugs,
            oauth_state_file=oauth_state_file,
            oidc_config=oidc_config,
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
