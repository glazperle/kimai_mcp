"""Security utilities for Kimai MCP HTTP servers.

This module provides security-related classes for:
- Rate limiting (Token Bucket algorithm)
- Session management with TTL and limits
- Security headers middleware
- Enumeration protection
"""

import asyncio
import logging
import random
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


# =============================================================================
# Rate Limiting
# =============================================================================


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting.

    Attributes:
        requests_per_minute: Maximum requests allowed per minute per client
        burst_limit: Maximum requests allowed in a short burst (token bucket size)
        enabled: Whether rate limiting is enabled
        cleanup_interval_seconds: How often to clean up old rate limit entries
    """

    requests_per_minute: int = 60
    burst_limit: int = 10
    enabled: bool = True
    cleanup_interval_seconds: int = 300  # 5 minutes


class TokenBucketRateLimiter:
    """Token bucket rate limiter for per-IP/per-session limiting.

    Uses the token bucket algorithm which allows short bursts while
    maintaining an average rate limit over time.
    """

    def __init__(self, config: RateLimitConfig):
        """Initialize the rate limiter.

        Args:
            config: Rate limiting configuration
        """
        self.config = config
        # key -> (tokens, last_update_time)
        self._buckets: Dict[str, Tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str) -> bool:
        """Check if a request is allowed for the given key.

        Args:
            key: Identifier for the client (typically IP address)

        Returns:
            True if request is allowed, False if rate limited
        """
        if not self.config.enabled:
            return True

        async with self._lock:
            now = time.monotonic()
            tokens, last_update = self._buckets.get(
                key, (float(self.config.burst_limit), now)
            )

            # Refill tokens based on time elapsed
            elapsed = now - last_update
            refill_rate = self.config.requests_per_minute / 60.0
            tokens = min(self.config.burst_limit, tokens + elapsed * refill_rate)

            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                return True
            else:
                self._buckets[key] = (tokens, now)
                logger.warning(f"Rate limit exceeded for {key}")
                return False

    async def cleanup_old_entries(self, max_age_seconds: int = 3600) -> int:
        """Remove entries older than max_age_seconds.

        Args:
            max_age_seconds: Maximum age of entries to keep

        Returns:
            Number of entries removed
        """
        async with self._lock:
            now = time.monotonic()
            to_remove = [
                key
                for key, (_, last_update) in self._buckets.items()
                if now - last_update > max_age_seconds
            ]
            for key in to_remove:
                del self._buckets[key]
            if to_remove:
                logger.debug(f"Cleaned up {len(to_remove)} rate limit entries")
            return len(to_remove)

    @property
    def entry_count(self) -> int:
        """Current number of tracked clients."""
        return len(self._buckets)


class RateLimitMiddleware:
    """ASGI middleware for rate limiting HTTP requests."""

    def __init__(
        self,
        app: ASGIApp,
        config: Optional[RateLimitConfig] = None,
    ):
        """Initialize the rate limiting middleware.

        Args:
            app: The ASGI application to wrap
            config: Rate limiting configuration
        """
        self.app = app
        self.config = config or RateLimitConfig()
        self.limiter = TokenBucketRateLimiter(self.config)
        self._cleanup_task: Optional[asyncio.Task] = None

    def _get_client_ip(self, scope: Scope) -> str:
        """Extract client IP from ASGI scope.

        Checks X-Forwarded-For header first (for reverse proxy scenarios),
        then falls back to direct connection IP.

        Args:
            scope: ASGI connection scope

        Returns:
            Client IP address string
        """
        # Check for X-Forwarded-For (when behind proxy)
        headers = dict(scope.get("headers", []))
        forwarded = headers.get(b"x-forwarded-for", b"").decode()
        if forwarded:
            # Take the first IP in the chain (original client)
            return forwarded.split(",")[0].strip()

        # Check for X-Real-IP
        real_ip = headers.get(b"x-real-ip", b"").decode()
        if real_ip:
            return real_ip.strip()

        # Fall back to direct connection
        client = scope.get("client")
        return client[0] if client else "unknown"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle ASGI request with rate limiting.

        Args:
            scope: ASGI connection scope
            receive: ASGI receive callable
            send: ASGI send callable
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not self.config.enabled:
            await self.app(scope, receive, send)
            return

        client_ip = self._get_client_ip(scope)

        if not await self.limiter.is_allowed(client_ip):
            response = JSONResponse(
                {"error": "Rate limit exceeded", "retry_after": 60},
                status_code=429,
                headers={"Retry-After": "60"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


# =============================================================================
# Security Headers
# =============================================================================


class SecurityHeadersMiddleware:
    """ASGI middleware to add security headers to all responses."""

    SECURITY_HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
    }

    def __init__(self, app: ASGIApp, extra_headers: Optional[Dict[str, str]] = None):
        """Initialize the security headers middleware.

        Args:
            app: The ASGI application to wrap
            extra_headers: Additional headers to add
        """
        self.app = app
        self.headers = {**self.SECURITY_HEADERS}
        if extra_headers:
            self.headers.update(extra_headers)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle ASGI request with security headers.

        Args:
            scope: ASGI connection scope
            receive: ASGI receive callable
            send: ASGI send callable
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                for name, value in self.headers.items():
                    headers.append((name.lower().encode(), value.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


# =============================================================================
# Session Management
# =============================================================================


@dataclass
class SessionConfig:
    """Configuration for session management.

    Attributes:
        max_sessions: Maximum number of concurrent sessions
        session_ttl_seconds: Time-to-live for sessions in seconds
        cleanup_interval_seconds: How often to run cleanup
    """

    max_sessions: int = 100
    session_ttl_seconds: int = 3600  # 1 hour
    cleanup_interval_seconds: int = 300  # 5 minutes


class SessionManager:
    """Manages client sessions with limits and TTL.

    Provides:
    - Maximum session count enforcement
    - Automatic session expiration (TTL)
    - Background cleanup of expired sessions
    - Sliding expiration (access extends TTL)
    """

    def __init__(self, config: Optional[SessionConfig] = None):
        """Initialize the session manager.

        Args:
            config: Session management configuration
        """
        self.config = config or SessionConfig()
        # session_id -> (session_object, last_access_time)
        self._sessions: Dict[str, Tuple[Any, float]] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the background cleanup task."""
        if self._running:
            return
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info(
            f"Session manager started (max={self.config.max_sessions}, "
            f"ttl={self.config.session_ttl_seconds}s)"
        )

    async def stop(self) -> None:
        """Stop the background cleanup task and clean up all sessions."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        # Clean up all remaining sessions
        async with self._lock:
            for session_id, (session, _) in list(self._sessions.items()):
                await self._cleanup_session(session_id, session)
            self._sessions.clear()
        logger.info("Session manager stopped")

    async def _cleanup_loop(self) -> None:
        """Periodically clean up expired sessions."""
        while self._running:
            try:
                await asyncio.sleep(self.config.cleanup_interval_seconds)
                await self.cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in session cleanup: {e}")

    async def _cleanup_session(self, session_id: str, session: Any) -> None:
        """Clean up a single session.

        Args:
            session_id: Session identifier
            session: Session object
        """
        # Call cleanup method if session has one
        if hasattr(session, "cleanup"):
            try:
                result = session.cleanup()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Error cleaning up session {session_id[:8]}: {e}")

    async def cleanup_expired(self) -> int:
        """Remove expired sessions.

        Returns:
            Number of sessions removed
        """
        async with self._lock:
            now = time.time()
            expired = [
                (sid, session)
                for sid, (session, last_access) in self._sessions.items()
                if now - last_access > self.config.session_ttl_seconds
            ]

            for sid, session in expired:
                del self._sessions[sid]
                await self._cleanup_session(sid, session)

            if expired:
                logger.info(f"Cleaned up {len(expired)} expired sessions")
            return len(expired)

    async def create(self, session_id: str, session: Any) -> bool:
        """Create a new session.

        Args:
            session_id: Unique session identifier
            session: Session object to store

        Returns:
            True if session was created, False if limit reached
        """
        async with self._lock:
            # Check if session already exists
            if session_id in self._sessions:
                return True

            # Check limit
            if len(self._sessions) >= self.config.max_sessions:
                # Try to clean up expired sessions first
                pass  # Release lock for cleanup

        # Cleanup outside lock to avoid deadlock
        await self.cleanup_expired()

        async with self._lock:
            # Check limit again after cleanup
            if len(self._sessions) >= self.config.max_sessions:
                logger.warning(
                    f"Session limit reached ({self.config.max_sessions}), "
                    f"rejecting new session"
                )
                return False

            self._sessions[session_id] = (session, time.time())
            logger.debug(
                f"Created session {session_id[:8]}... "
                f"(total: {len(self._sessions)})"
            )
            return True

    async def get(self, session_id: str) -> Optional[Any]:
        """Get session by ID, updating last access time.

        Implements sliding expiration - accessing a session extends its TTL.

        Args:
            session_id: Session identifier

        Returns:
            Session object if found, None otherwise
        """
        async with self._lock:
            if session_id in self._sessions:
                session, _ = self._sessions[session_id]
                # Update timestamp on access (sliding expiration)
                self._sessions[session_id] = (session, time.time())
                return session
            return None

    async def remove(self, session_id: str) -> Optional[Any]:
        """Remove and return a session.

        Args:
            session_id: Session identifier

        Returns:
            Session object if found, None otherwise
        """
        async with self._lock:
            if session_id in self._sessions:
                session, _ = self._sessions.pop(session_id)
                logger.debug(
                    f"Removed session {session_id[:8]}... "
                    f"(remaining: {len(self._sessions)})"
                )
                return session
            return None

    async def exists(self, session_id: str) -> bool:
        """Check if a session exists.

        Args:
            session_id: Session identifier

        Returns:
            True if session exists, False otherwise
        """
        async with self._lock:
            return session_id in self._sessions

    @property
    def count(self) -> int:
        """Current number of active sessions."""
        return len(self._sessions)


# =============================================================================
# Enumeration Protection
# =============================================================================


class EnumerationProtection:
    """Protect against user/endpoint enumeration attacks.

    Tracks 404 errors per client and blocks clients that exceed
    a threshold, indicating possible enumeration attempts.
    """

    def __init__(
        self,
        max_404_per_minute: int = 10,
        block_duration_seconds: int = 300,
    ):
        """Initialize enumeration protection.

        Args:
            max_404_per_minute: Maximum 404 errors allowed per minute
            block_duration_seconds: How long to block offending clients
        """
        self.max_404 = max_404_per_minute
        self.block_duration = block_duration_seconds
        # client_ip -> list of timestamps
        self._404_counts: Dict[str, List[float]] = defaultdict(list)
        # client_ip -> block_until_timestamp
        self._blocked: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def is_blocked(self, client_ip: str) -> bool:
        """Check if a client is currently blocked.

        Args:
            client_ip: Client IP address

        Returns:
            True if blocked, False otherwise
        """
        async with self._lock:
            if client_ip in self._blocked:
                if time.time() < self._blocked[client_ip]:
                    return True
                else:
                    # Block expired
                    del self._blocked[client_ip]
            return False

    async def record_404(self, client_ip: str) -> bool:
        """Record a 404 error and check if client should be blocked.

        Args:
            client_ip: Client IP address

        Returns:
            True if client should be blocked, False otherwise
        """
        async with self._lock:
            now = time.time()

            # Clean old entries (older than 1 minute)
            self._404_counts[client_ip] = [
                t for t in self._404_counts[client_ip] if now - t < 60
            ]
            self._404_counts[client_ip].append(now)

            if len(self._404_counts[client_ip]) > self.max_404:
                logger.warning(
                    f"Possible enumeration attack from {client_ip} - "
                    f"{len(self._404_counts[client_ip])} 404s in 1 minute"
                )
                self._blocked[client_ip] = now + self.block_duration
                return True
            return False

    async def cleanup_old_entries(self) -> int:
        """Clean up old tracking entries.

        Returns:
            Number of entries cleaned up
        """
        async with self._lock:
            now = time.time()
            cleaned = 0

            # Clean expired blocks
            expired_blocks = [
                ip for ip, until in self._blocked.items() if now >= until
            ]
            for ip in expired_blocks:
                del self._blocked[ip]
                cleaned += 1

            # Clean old 404 counts
            empty_ips = [
                ip
                for ip, counts in self._404_counts.items()
                if not any(now - t < 60 for t in counts)
            ]
            for ip in empty_ips:
                del self._404_counts[ip]
                cleaned += 1

            return cleaned


async def random_delay(min_seconds: float = 0.1, max_seconds: float = 0.3) -> None:
    """Add a random delay to prevent timing attacks.

    Args:
        min_seconds: Minimum delay in seconds
        max_seconds: Maximum delay in seconds
    """
    await asyncio.sleep(random.uniform(min_seconds, max_seconds))
