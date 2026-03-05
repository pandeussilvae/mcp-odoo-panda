"""
Test module for Odoo MCP Connection Pool.
"""

import asyncio
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, Mock, patch
from typing import Dict, Any

# Import the class to test and related exceptions
from odoo_mcp.core.connection_pool import ConnectionPool, ConnectionWrapper
from odoo_mcp.error_handling.exceptions import PoolTimeoutError, ConnectionError as PoolConnectionError

# Mark all tests in this module as asyncio
pytestmark = pytest.mark.asyncio

# --- Mock Handlers ---

class MockHandler:
    """A simple mock handler for successful connections."""
    def __init__(self, config):
        self.config = config
        self.closed = False
        # Simulate some basic attributes the pool might interact with
        self.common = MagicMock()
        self.common.version.return_value = {"server_version": "mock_odoo/16.0"}
        print(f"MockHandler {id(self)} initialized.")

    async def close(self):
        print(f"MockHandler {id(self)} close called.")
        self.closed = True

    async def cleanup(self):
        """Called by pool.close_all()."""
        self.closed = True

    async def health_check(self) -> bool:
        # Simulate health check specific to the handler if needed by ConnectionWrapper
        print(f"MockHandler {id(self)} health_check called.")
        # For simplicity, assume ConnectionWrapper's health_check uses common.version
        try:
             self.common.version()
             return True
        except Exception:
             return False

class MockFailingHandler:
    """A mock handler that always fails during initialization."""
    _init_attempts = 0

    def __init__(self, config):
        MockFailingHandler._init_attempts += 1
        print(f"MockFailingHandler attempt {MockFailingHandler._init_attempts}: Failing init...")
        raise PoolConnectionError("Simulated connection failure during init")

    @classmethod
    def reset_attempts(cls):
        cls._init_attempts = 0

# --- Test Fixtures (Optional) ---

# Example fixture to provide a default config (keys match core ConnectionPool: max_connections, connection_timeout)
@pytest.fixture
def default_config():
    return {
        'odoo_url': 'http://mock-odoo:8069',
        'database': 'mock_db',
        'username': 'mock_user',
        'api_key': 'mock_key',
        'max_connections': 2,
        'connection_timeout': 30,
        'connection_health_interval': 60,
        'retry_count': 1,
    }

# --- Test Cases ---

async def test_pool_initialization(default_config):
    """Test basic pool initialization."""
    pool = ConnectionPool(default_config, MockHandler)
    assert pool.max_size == default_config['max_connections']
    assert pool.timeout == default_config['connection_timeout']
    assert len(pool.connections) == 0
    await pool.close()

async def test_acquire_release_within_limit(default_config):
    """Test acquiring and releasing connections within the pool size (async with get_connection)."""
    pool = ConnectionPool(default_config, MockHandler)
    seen_handlers = []

    async with pool.get_connection() as conn1:
        assert isinstance(conn1, MockHandler)
        assert len(pool.connections) == 1
        seen_handlers.append(id(conn1))

    async with pool.get_connection() as conn2:
        assert isinstance(conn2, MockHandler)
        assert len(pool.connections) == 2
        seen_handlers.append(id(conn2))

    # After exiting both contexts, pool has 2 idle connections
    assert len(pool.connections) == 2
    assert sum(1 for w in pool.connections if not w.in_use) == 2

    # Acquire again, should reuse one of the existing connections
    async with pool.get_connection() as conn3:
        assert len(pool.connections) == 2
        assert id(conn3) in seen_handlers

    await pool.close()

async def test_acquire_timeout(default_config):
    """Test timeout when acquiring more connections than pool size."""
    pool = ConnectionPool(default_config, MockHandler)
    # Hold all connections open via context managers
    async with pool.get_connection():
        async with pool.get_connection():
            assert len(pool.connections) == default_config['max_connections']
            # Try acquiring one more, should time out (no wait loop in current pool, immediate raise)
            with pytest.raises(PoolTimeoutError):
                async with pool.get_connection():
                    pass
    await pool.close()

async def test_connection_creation_retry(default_config):
    """Test the retry mechanism when handler initialization fails."""
    MockFailingHandler.reset_attempts()
    config = default_config.copy()
    config['retry_count'] = 2  # Allow 2 retries (3 attempts total)

    pool = ConnectionPool(config, MockFailingHandler)

    # get_connection is now a context manager; exception is raised when entering the context
    with pytest.raises(PoolConnectionError):
        async with pool.get_connection() as _:
            pass

    # Check that the handler init was attempted retry_count + 1 times
    assert MockFailingHandler._init_attempts == config['retry_count'] + 1

    await pool.close()

async def test_pool_close(default_config):
    """Test closing the pool clears connections."""
    pool = ConnectionPool(default_config, MockHandler)
    # Use and release a connection
    async with pool.get_connection() as conn1:
        pass
    assert len(pool.connections) == 1

    # Acquire again (reuse), then acquire a second
    async with pool.get_connection() as conn2:
        async with pool.get_connection() as conn3:
            assert len(pool.connections) == 2
            assert conn2 is not conn3
    # Both released
    assert len(pool.connections) == 2
    assert all(not w.in_use for w in pool.connections)

    await pool.start()
    assert pool._cleanup_task is not None and not pool._cleanup_task.done()

    await pool.close()
    assert len(pool.connections) == 0
    assert pool._cleanup_task is None or pool._cleanup_task.done()

# TODO: Add tests for health check logic (requires more sophisticated mocking or integration)
