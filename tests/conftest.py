"""Pytest configuration and fixtures for Kimai MCP tests."""

import pytest
import asyncio
import os
import sys
from unittest.mock import AsyncMock, Mock

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_kimai_client():
    """Create a mock Kimai client for testing."""
    from kimai_mcp.client import KimaiClient
    
    client = AsyncMock(spec=KimaiClient)
    
    # Set up common mock responses
    client.get_version.return_value = Mock(version="2.37.0")
    client.ping.return_value = {"message": "pong"}
    
    return client


@pytest.fixture
def test_config():
    """Provide test configuration."""
    return {
        "base_url": "https://test.kimai.example.com",
        "api_token": "test-token-12345",
        "default_user_id": "1"
    }


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Set up test environment variables."""
    original_env = os.environ.copy()
    
    # Set test environment variables
    os.environ["KIMAI_URL"] = "https://test.kimai.example.com"
    os.environ["KIMAI_API_TOKEN"] = "test-token-12345"
    os.environ["KIMAI_DEFAULT_USER"] = "1"
    
    yield
    
    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)