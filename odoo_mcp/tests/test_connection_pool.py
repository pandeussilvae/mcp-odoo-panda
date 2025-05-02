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

# Example fixture to provide a default config
@pytest.fixture
def default_config():
    return {
        'odoo_url': 'http://mock-odoo:8069',
        'database': 'mock_db',
        'username': 'mock_user',
        'api_key': 'mock_key',
        'pool_size': 2,
        'timeout': 0.5, # Short timeout for testing
        'connection_health_interval': 60, # Disable health checks during most tests unless needed
        'retry_count': 1, # Low retry count for testing failures
    }

# --- Test Cases ---

async def test_pool_initialization(default_config):
    """Test basic pool initialization."""
    pool = ConnectionPool(default_config, MockHandler)
    assert pool.pool_size == default_config['pool_size']
    assert pool.timeout == default_config['timeout']
    assert pool._current_size == 0
    assert len(pool._pool) == 0
    await pool.close() # Cleanup

async def test_acquire_release_within_limit(default_config):
    """Test acquiring and releasing connections within the pool size."""
    pool = ConnectionPool(default_config, MockHandler)
    conn1 = await pool.get_connection()
    assert isinstance(conn1, ConnectionWrapper)
    assert isinstance(conn1.connection, MockHandler)
    assert pool._current_size == 1
    assert len(pool._pool) == 0

    conn2 = await pool.get_connection()
    assert isinstance(conn2, ConnectionWrapper)
    assert pool._current_size == 2
    assert len(pool._pool) == 0
    assert conn1 is not conn2 # Should be different connections

    await pool.release_connection(conn1)
    assert pool._current_size == 2 # Size remains max until connections are closed/discarded
    assert len(pool._pool) == 1 # One connection is now idle

    await pool.release_connection(conn2)
    assert pool._current_size == 2
    assert len(pool._pool) == 2 # Both connections are idle

    # Acquire again, should reuse from pool
    conn3 = await pool.get_connection()
    assert pool._current_size == 2
    assert len(pool._pool) == 1
    # Check if it's one of the previously released connections
    assert conn3 is conn1 or conn3 is conn2

    await pool.release_connection(conn3)
    await pool.close()

async def test_acquire_timeout(default_config):
    """Test timeout when acquiring more connections than pool size."""
    pool = ConnectionPool(default_config, MockHandler)
    conns = []
    # Acquire all connections
    for _ in range(default_config['pool_size']):
        conns.append(await pool.get_connection())

    assert pool._current_size == default_config['pool_size']

    # Try acquiring one more, should time out
    with pytest.raises(PoolTimeoutError):
        await pool.get_connection()

    # Release connections and close pool
    for conn in conns:
        await pool.release_connection(conn)
    await pool.close()

async def test_connection_creation_retry(default_config):
    """Test the retry mechanism when handler initialization fails."""
    MockFailingHandler.reset_attempts()
    config = default_config.copy()
    config['retry_count'] = 2 # Allow 2 retries (3 attempts total)

    pool = ConnectionPool(config, MockFailingHandler)

    # Expect ConnectionError because _create_connection raises it after all retries,
    # and the updated get_connection logic propagates it immediately.
    with pytest.raises(PoolConnectionError, match="Failed to create connection after 3 attempts"):
        await pool.get_connection()

    # Check that the handler init was attempted retry_count + 1 times
    assert MockFailingHandler._init_attempts == config['retry_count'] + 1

    await pool.close()

async def test_pool_close(default_config):
    """Test closing the pool cancels tasks and cleans up idle connections."""
    pool = ConnectionPool(default_config, MockHandler)
    # Acquire and release a connection to populate the idle pool
    conn1 = await pool.get_connection()
    await pool.release_connection(conn1)
    assert len(pool._pool) == 1
    assert pool._current_size == 1 # Size should still be 1

    # Acquire again, should reuse conn1
    conn2 = await pool.get_connection()
    assert conn2 is conn1 # Should reuse the connection
    assert pool._current_size == 1 # Size still 1
    assert len(pool._pool) == 0 # Pool is empty again

    # Acquire a third connection, this should create a new one
    conn3 = await pool.get_connection()
    assert conn3 is not conn1
    assert isinstance(conn3.connection, MockHandler)
    assert pool._current_size == 2 # Now size should be 2
    assert len(pool._pool) == 0

    # Keep conn2 (which is conn1) and conn3 checked out for the close test
    # Don't release them yet.

    # Start health checks (though interval is long)
    await pool.start_health_checks()
    health_task = pool._health_check_task
    assert health_task is not None and not health_task.done()

    await pool.close()

    assert pool._closing is True
    assert len(pool._pool) == 0 # Idle connections should be cleared
    # Check if the connections held by the test were closed (they weren't idle)
    # conn1 was released and then re-acquired as conn2. It wasn't idle at close.
    # conn3 wasn't idle at close.
    # The pool's close() only explicitly closes *idle* connections.
    # Active connections are marked inactive upon release *after* close is called.
    # So, conn1/conn2 and conn3 should still be marked active *until* released.
    assert conn2.is_active is True # conn2 is conn1, was active
    assert conn3.is_active is True # conn3 was active

    # Check if health check task was cancelled
    assert health_task.cancelled() or health_task.done() # Task might finish quickly after cancel

    # Releasing the active connections after pool close should discard them and mark inactive
    await pool.release_connection(conn2) # Release conn1/conn2
    assert conn2.is_active is False
    await pool.release_connection(conn3) # Release conn3
    assert conn3.is_active is False
    # Pool size tracking during shutdown is less critical than connection state.

# TODO: Add tests for health check logic (requires more sophisticated mocking or integration)
# TODO: Add tests for releasing inactive connections
