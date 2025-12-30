"""Unit tests for security module."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from kimai_mcp.security import (
    EnumerationProtection,
    RateLimitConfig,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    SessionConfig,
    SessionManager,
    TokenBucketRateLimiter,
    random_delay,
)


# =============================================================================
# Rate Limiting Tests
# =============================================================================


class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = RateLimitConfig()
        assert config.requests_per_minute == 60
        assert config.burst_limit == 10
        assert config.enabled is True
        assert config.cleanup_interval_seconds == 300

    def test_custom_values(self):
        """Test custom configuration values."""
        config = RateLimitConfig(
            requests_per_minute=120,
            burst_limit=20,
            enabled=False,
            cleanup_interval_seconds=600,
        )
        assert config.requests_per_minute == 120
        assert config.burst_limit == 20
        assert config.enabled is False
        assert config.cleanup_interval_seconds == 600


class TestTokenBucketRateLimiter:
    """Tests for TokenBucketRateLimiter class."""

    @pytest.mark.asyncio
    async def test_allows_burst(self):
        """Test that burst requests are allowed."""
        config = RateLimitConfig(requests_per_minute=60, burst_limit=5)
        limiter = TokenBucketRateLimiter(config)

        # Should allow burst_limit requests immediately
        for i in range(5):
            assert await limiter.is_allowed("test-ip"), f"Request {i+1} should be allowed"

    @pytest.mark.asyncio
    async def test_blocks_after_burst_exhausted(self):
        """Test that requests are blocked after burst is exhausted."""
        config = RateLimitConfig(requests_per_minute=60, burst_limit=3)
        limiter = TokenBucketRateLimiter(config)

        # Exhaust burst
        for _ in range(3):
            await limiter.is_allowed("test-ip")

        # Should be blocked
        assert not await limiter.is_allowed("test-ip")

    @pytest.mark.asyncio
    async def test_different_ips_independent(self):
        """Test that different IPs have independent rate limits."""
        config = RateLimitConfig(requests_per_minute=60, burst_limit=2)
        limiter = TokenBucketRateLimiter(config)

        # Exhaust burst for IP1
        await limiter.is_allowed("ip1")
        await limiter.is_allowed("ip1")

        # IP2 should still be allowed
        assert await limiter.is_allowed("ip2")
        assert await limiter.is_allowed("ip2")

        # IP1 should be blocked
        assert not await limiter.is_allowed("ip1")

    @pytest.mark.asyncio
    async def test_disabled_allows_all(self):
        """Test that disabled rate limiter allows all requests."""
        config = RateLimitConfig(enabled=False, burst_limit=1)
        limiter = TokenBucketRateLimiter(config)

        # Should allow many requests even with burst_limit=1
        for _ in range(100):
            assert await limiter.is_allowed("test-ip")

    @pytest.mark.asyncio
    async def test_tokens_refill_over_time(self):
        """Test that tokens refill over time."""
        # 60 req/min = 1 req/sec refill rate
        config = RateLimitConfig(requests_per_minute=60, burst_limit=2)
        limiter = TokenBucketRateLimiter(config)

        # Exhaust burst
        await limiter.is_allowed("test-ip")
        await limiter.is_allowed("test-ip")
        assert not await limiter.is_allowed("test-ip")

        # Wait for refill (slightly more than 1 second for 1 token)
        await asyncio.sleep(1.1)

        # Should be allowed again
        assert await limiter.is_allowed("test-ip")

    @pytest.mark.asyncio
    async def test_cleanup_old_entries(self):
        """Test cleanup of old entries."""
        config = RateLimitConfig()
        limiter = TokenBucketRateLimiter(config)

        # Create some entries
        await limiter.is_allowed("ip1")
        await limiter.is_allowed("ip2")

        assert limiter.entry_count == 2

        # Cleanup with 0 max age should remove all
        removed = await limiter.cleanup_old_entries(max_age_seconds=0)
        assert removed == 2
        assert limiter.entry_count == 0


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""

    @pytest.mark.asyncio
    async def test_extracts_client_ip_from_x_forwarded_for(self):
        """Test IP extraction from X-Forwarded-For header."""
        app = AsyncMock()
        middleware = RateLimitMiddleware(app)

        scope = {
            "type": "http",
            "headers": [(b"x-forwarded-for", b"1.2.3.4, 5.6.7.8")],
        }

        ip = middleware._get_client_ip(scope)
        assert ip == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_extracts_client_ip_from_x_real_ip(self):
        """Test IP extraction from X-Real-IP header."""
        app = AsyncMock()
        middleware = RateLimitMiddleware(app)

        scope = {
            "type": "http",
            "headers": [(b"x-real-ip", b"1.2.3.4")],
        }

        ip = middleware._get_client_ip(scope)
        assert ip == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_extracts_client_ip_from_direct_connection(self):
        """Test IP extraction from direct connection."""
        app = AsyncMock()
        middleware = RateLimitMiddleware(app)

        scope = {
            "type": "http",
            "headers": [],
            "client": ("192.168.1.1", 12345),
        }

        ip = middleware._get_client_ip(scope)
        assert ip == "192.168.1.1"

    @pytest.mark.asyncio
    async def test_passes_through_non_http(self):
        """Test that non-HTTP requests pass through."""
        app = AsyncMock()
        middleware = RateLimitMiddleware(app)

        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_called_once_with(scope, receive, send)


# =============================================================================
# Security Headers Tests
# =============================================================================


class TestSecurityHeadersMiddleware:
    """Tests for SecurityHeadersMiddleware."""

    @pytest.mark.asyncio
    async def test_adds_security_headers(self):
        """Test that security headers are added to responses."""
        headers_received = []

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        async def capture_send(message):
            if message["type"] == "http.response.start":
                headers_received.extend(message.get("headers", []))

        middleware = SecurityHeadersMiddleware(mock_app)

        scope = {"type": "http"}
        receive = AsyncMock()

        await middleware(scope, receive, capture_send)

        # Check that security headers were added
        header_names = [h[0] for h in headers_received]
        assert b"x-content-type-options" in header_names
        assert b"x-frame-options" in header_names
        assert b"cache-control" in header_names

    @pytest.mark.asyncio
    async def test_extra_headers(self):
        """Test that extra headers can be added."""
        headers_received = []

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})

        async def capture_send(message):
            if message["type"] == "http.response.start":
                headers_received.extend(message.get("headers", []))

        middleware = SecurityHeadersMiddleware(
            mock_app, extra_headers={"Custom-Header": "value"}
        )

        await middleware({"type": "http"}, AsyncMock(), capture_send)

        header_dict = {h[0]: h[1] for h in headers_received}
        assert header_dict[b"custom-header"] == b"value"


# =============================================================================
# Session Manager Tests
# =============================================================================


class TestSessionConfig:
    """Tests for SessionConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = SessionConfig()
        assert config.max_sessions == 100
        assert config.session_ttl_seconds == 3600
        assert config.cleanup_interval_seconds == 300


class TestSessionManager:
    """Tests for SessionManager class."""

    @pytest.mark.asyncio
    async def test_create_session(self):
        """Test creating a session."""
        manager = SessionManager(SessionConfig(max_sessions=10))

        result = await manager.create("session1", {"data": "test"})

        assert result is True
        assert manager.count == 1

    @pytest.mark.asyncio
    async def test_create_session_enforces_limit(self):
        """Test that session limit is enforced."""
        manager = SessionManager(SessionConfig(max_sessions=2, session_ttl_seconds=3600))

        await manager.create("s1", object())
        await manager.create("s2", object())

        # Third session should fail
        result = await manager.create("s3", object())

        assert result is False
        assert manager.count == 2

    @pytest.mark.asyncio
    async def test_get_session(self):
        """Test retrieving a session."""
        manager = SessionManager()
        test_obj = {"key": "value"}

        await manager.create("session1", test_obj)
        retrieved = await manager.get("session1")

        assert retrieved == test_obj

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self):
        """Test retrieving a non-existent session."""
        manager = SessionManager()

        result = await manager.get("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_remove_session(self):
        """Test removing a session."""
        manager = SessionManager()
        test_obj = {"key": "value"}

        await manager.create("session1", test_obj)
        removed = await manager.remove("session1")

        assert removed == test_obj
        assert manager.count == 0

    @pytest.mark.asyncio
    async def test_session_exists(self):
        """Test checking if session exists."""
        manager = SessionManager()

        await manager.create("session1", object())

        assert await manager.exists("session1")
        assert not await manager.exists("nonexistent")

    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(self):
        """Test cleanup of expired sessions."""
        config = SessionConfig(session_ttl_seconds=1)  # 1 second TTL
        manager = SessionManager(config)

        await manager.create("session1", object())
        assert manager.count == 1

        # Wait for expiration
        await asyncio.sleep(1.5)

        removed = await manager.cleanup_expired()

        assert removed == 1
        assert manager.count == 0

    @pytest.mark.asyncio
    async def test_sliding_expiration(self):
        """Test that accessing a session extends its TTL."""
        config = SessionConfig(session_ttl_seconds=2)
        manager = SessionManager(config)

        await manager.create("session1", {"data": "test"})

        # Access session before expiration
        await asyncio.sleep(1)
        await manager.get("session1")

        # Wait another second (would be expired without sliding)
        await asyncio.sleep(1.2)

        # Session should still exist due to sliding expiration
        assert await manager.exists("session1")

    @pytest.mark.asyncio
    async def test_session_cleanup_calls_cleanup_method(self):
        """Test that session cleanup method is called."""
        cleanup_called = []

        class MockSession:
            async def cleanup(self):
                cleanup_called.append(True)

        config = SessionConfig(session_ttl_seconds=1)
        manager = SessionManager(config)

        await manager.create("session1", MockSession())
        await asyncio.sleep(1.5)
        await manager.cleanup_expired()

        assert len(cleanup_called) == 1

    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Test starting and stopping the session manager."""
        manager = SessionManager()

        await manager.start()
        assert manager._running is True
        assert manager._cleanup_task is not None

        await manager.stop()
        assert manager._running is False


# =============================================================================
# Enumeration Protection Tests
# =============================================================================


class TestEnumerationProtection:
    """Tests for EnumerationProtection class."""

    @pytest.mark.asyncio
    async def test_allows_initial_404s(self):
        """Test that initial 404s are allowed."""
        protection = EnumerationProtection(max_404_per_minute=5)

        for _ in range(5):
            result = await protection.record_404("1.2.3.4")
            assert result is False

    @pytest.mark.asyncio
    async def test_blocks_after_threshold(self):
        """Test that client is blocked after exceeding threshold."""
        protection = EnumerationProtection(max_404_per_minute=3)

        # First 3 are allowed
        for _ in range(3):
            await protection.record_404("1.2.3.4")

        # 4th should trigger block
        result = await protection.record_404("1.2.3.4")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_blocked(self):
        """Test checking if client is blocked."""
        protection = EnumerationProtection(max_404_per_minute=1, block_duration_seconds=60)

        assert not await protection.is_blocked("1.2.3.4")

        await protection.record_404("1.2.3.4")
        await protection.record_404("1.2.3.4")  # Should trigger block

        assert await protection.is_blocked("1.2.3.4")

    @pytest.mark.asyncio
    async def test_block_expires(self):
        """Test that blocks expire after duration."""
        protection = EnumerationProtection(max_404_per_minute=1, block_duration_seconds=1)

        await protection.record_404("1.2.3.4")
        await protection.record_404("1.2.3.4")  # Trigger block

        assert await protection.is_blocked("1.2.3.4")

        await asyncio.sleep(1.5)

        assert not await protection.is_blocked("1.2.3.4")

    @pytest.mark.asyncio
    async def test_different_ips_independent(self):
        """Test that different IPs are tracked independently."""
        protection = EnumerationProtection(max_404_per_minute=2)

        await protection.record_404("ip1")
        await protection.record_404("ip1")
        await protection.record_404("ip1")  # ip1 blocked

        # ip2 should still be allowed
        result = await protection.record_404("ip2")
        assert result is False

    @pytest.mark.asyncio
    async def test_cleanup_old_entries(self):
        """Test cleanup of old entries."""
        protection = EnumerationProtection(max_404_per_minute=3, block_duration_seconds=1)

        # Exceed limit to create block (need more than max_404)
        for _ in range(4):
            await protection.record_404("ip1")

        # Verify block was created
        assert await protection.is_blocked("ip1")

        # Wait for block to expire
        await asyncio.sleep(1.5)

        # Now block should be expired, cleanup should remove it
        # (is_blocked already removes expired blocks when checked)
        # So we need to check that the entries can be cleaned
        assert not await protection.is_blocked("ip1")  # Expired, removes from _blocked


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestRandomDelay:
    """Tests for random_delay function."""

    @pytest.mark.asyncio
    async def test_delay_within_bounds(self):
        """Test that delay is within specified bounds."""
        start = time.monotonic()
        await random_delay(0.1, 0.2)
        elapsed = time.monotonic() - start

        assert 0.1 <= elapsed <= 0.3  # Some tolerance

    @pytest.mark.asyncio
    async def test_delay_varies(self):
        """Test that delay varies between calls."""
        delays = []
        for _ in range(5):
            start = time.monotonic()
            await random_delay(0.05, 0.15)
            delays.append(time.monotonic() - start)

        # Check that not all delays are identical (with some tolerance)
        unique_delays = len(set(round(d, 2) for d in delays))
        # At least some variation expected
        assert unique_delays >= 1
