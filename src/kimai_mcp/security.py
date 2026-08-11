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
from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


# =============================================================================
# Client IP Extraction
# =============================================================================


def get_client_ip(scope: Scope, trusted_proxies: Iterable[str] | None = None) -> str:
    """Extract the client IP from an ASGI scope.

    SECURITY: The X-Forwarded-For / X-Real-IP headers are only honored when
    the direct peer is a configured trusted proxy. Otherwise these headers
    are attacker-controlled and would allow trivially bypassing IP-based
    rate limiting and enumeration protection.

    Args:
        scope: ASGI connection scope
        trusted_proxies: IPs of reverse proxies whose forwarding headers
            may be trusted (e.g. ["127.0.0.1"]). If empty/None, forwarding
            headers are ignored entirely.

    Returns:
        Client IP address string
    """
    client = scope.get("client")
    direct_ip = client[0] if client else "unknown"

    if trusted_proxies and direct_ip in set(trusted_proxies):
        headers = dict(scope.get("headers") or [])
        forwarded = headers.get(b"x-forwarded-for", b"").decode()
        if forwarded:
            # Take the LAST hop in the chain: that entry is the peer our trusted
            # proxy actually saw and appended. The leftmost entries are
            # client-supplied and therefore spoofable, which would let an
            # attacker rotate fake IPs to bypass rate limiting / enumeration
            # protection.
            return forwarded.split(",")[-1].strip()
        real_ip = headers.get(b"x-real-ip", b"").decode()
        if real_ip:
            return real_ip.strip()

    return direct_ip


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
        self._buckets: dict[str, tuple[float, float]] = {}
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
        config: RateLimitConfig | None = None,
        trusted_proxies: Iterable[str] | None = None,
    ):
        """Initialize the rate limiting middleware.

        Args:
            app: The ASGI application to wrap
            config: Rate limiting configuration
            trusted_proxies: IPs of reverse proxies whose X-Forwarded-For /
                X-Real-IP headers may be trusted. If not set, forwarding
                headers are ignored (see get_client_ip).
        """
        self.app = app
        self.config = config or RateLimitConfig()
        self.limiter = TokenBucketRateLimiter(self.config)
        self.trusted_proxies = list(trusted_proxies) if trusted_proxies else []
        self._cleanup_task: asyncio.Task | None = None

    def _get_client_ip(self, scope: Scope) -> str:
        """Extract client IP from ASGI scope (proxy-header aware, see get_client_ip)."""
        return get_client_ip(scope, self.trusted_proxies)

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

    SECURITY_HEADERS: ClassVar[dict[str, str]] = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
    }

    def __init__(self, app: ASGIApp, extra_headers: dict[str, str] | None = None):
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
        self._404_counts: dict[str, list[float]] = defaultdict(list)
        # client_ip -> block_until_timestamp
        self._blocked: dict[str, float] = {}
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
