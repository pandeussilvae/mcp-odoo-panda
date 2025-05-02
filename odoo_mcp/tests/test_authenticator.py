"""
Test module for Odoo MCP Authenticator.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, Mock, patch
import socket
from xmlrpc.client import Fault, ProtocolError as XmlRpcProtocolError
from typing import Dict, Any

# Import the class to test and related exceptions
from odoo_mcp.core.authenticator import OdooAuthenticator
from odoo_mcp.error_handling.exceptions import AuthError, NetworkError, PoolTimeoutError, ConnectionError as PoolConnectionError

# Mark all tests in this module as asyncio
pytestmark = pytest.mark.asyncio

# --- Mock Dependencies ---

class MockCommonProxy:
    """Mocks xmlrpc.client.ServerProxy for the 'common' endpoint."""
    def __init__(self, simulate_error=None, return_value=None):
        self._simulate_error = simulate_error
        self._return_value = return_value

    def authenticate(self, db, username, password, *args):
        print(f"MockCommonProxy authenticate called: db={db}, user={username}")
        if self._simulate_error:
            print(f" MockCommonProxy simulating error: {type(self._simulate_error)}")
            raise self._simulate_error
        elif self._return_value is not None:
            print(f" MockCommonProxy returning: {self._return_value}")
            return self._return_value
        # Default mock behavior for valid credentials
        elif username == "test_user" and password == "test_key" and db == "test_db":
             print(" MockCommonProxy returning UID 99")
             return 99 # Default valid UID
        else:
             print(" MockCommonProxy returning False (invalid creds)")
             return False # Simulate invalid credentials

class MockConnection:
    """Mocks the connection handler (e.g., XMLRPCHandler)."""
    def __init__(self, common_proxy_error=None, common_proxy_return=None, missing_common=False):
        if missing_common:
            # Simulate object without 'common' attribute
            pass
        else:
            self.common = MockCommonProxy(simulate_error=common_proxy_error, return_value=common_proxy_return)

class MockConnectionWrapper:
    """Mocks the ConnectionWrapper."""
    def __init__(self, connection_error=None, connection_return=None, missing_common=False):
        self.connection = MockConnection(
            common_proxy_error=connection_error,
            common_proxy_return=connection_return,
            missing_common=missing_common
        )

    # Make MockConnectionWrapper an async context manager
    async def __aenter__(self):
        print("MockConnectionWrapper.__aenter__ called")
        return self # Return self to be used as 'wrapper'

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        print("MockConnectionWrapper.__aexit__ called")
        # Simulate releasing the connection (no-op for mock)
        pass

class MockPool:
    """Mocks the ConnectionPool."""
    def __init__(self, get_connection_error=None, connection_error=None, connection_return=None, missing_common=False):
        self._get_connection_error = get_connection_error
        self._connection_error = connection_error
        self._connection_return = connection_return
        self._missing_common = missing_common

    async def get_connection(self):
        print("MockPool get_connection called.")
        if self._get_connection_error:
            print(f" MockPool simulating get_connection error: {type(self._get_connection_error)}")
            raise self._get_connection_error
        print(" MockPool returning MockConnectionWrapper.")
        return MockConnectionWrapper(
            connection_error=self._connection_error,
            connection_return=self._connection_return,
            missing_common=self._missing_common
        ) # This now returns an async context manager

    async def close(self): # Add close method needed by fixture cleanup
        pass

# --- Test Fixtures ---

@pytest.fixture
def auth_config():
    """Provides a default config for Authenticator tests."""
    return {
        'odoo_url': 'http://mock-odoo:8069',
        'database': 'test_db',
        # username/api_key not strictly needed by authenticator itself, but good practice
        'username': 'config_user',
        'api_key': 'config_key',
    }

# --- Test Cases ---

async def test_authenticate_success(auth_config):
    """Test successful authentication."""
    mock_pool = MockPool() # Default mock returns UID 99 for test_user/test_key
    authenticator = OdooAuthenticator(auth_config, mock_pool)
    uid = await authenticator.authenticate("test_user", "test_key")
    assert uid == 99

async def test_authenticate_invalid_credentials(auth_config):
    """Test authentication failure with invalid credentials."""
    mock_pool = MockPool() # Default mock returns False for wrong creds
    authenticator = OdooAuthenticator(auth_config, mock_pool)
    with pytest.raises(AuthError, match="Invalid username or API key"):
        await authenticator.authenticate("wrong_user", "wrong_key")

async def test_authenticate_odoo_fault(auth_config):
    """Test authentication failure due to XML-RPC Fault from Odoo."""
    fault = Fault(1, "Odoo Server Error: Invalid database")
    mock_pool = MockPool(connection_error=fault) # Correct indentation
    authenticator = OdooAuthenticator(auth_config, mock_pool)
    # Expect NetworkError because non-auth Fault is wrapped in NetworkError
    # Update the expected message to match the actual one raised
    expected_msg = "Authentication failed due to XML-RPC Fault: Odoo Server Error: Invalid database"
    with pytest.raises(NetworkError, match=re.escape(expected_msg)): # Use re.escape for literal matching
        await authenticator.authenticate("test_user", "test_key")

async def test_authenticate_network_error(auth_config):
    """Test authentication failure due to a network error (e.g., socket error)."""
    network_err = socket.gaierror("DNS lookup failed")
    mock_pool = MockPool(connection_error=network_err)
    authenticator = OdooAuthenticator(auth_config, mock_pool)
    with pytest.raises(NetworkError, match="Authentication failed due to a network or protocol error: DNS lookup failed"):
        await authenticator.authenticate("test_user", "test_key")

async def test_authenticate_pool_timeout(auth_config):
    """Test authentication failure due to pool timeout."""
    pool_err = PoolTimeoutError("Pool timeout")
    mock_pool = MockPool(get_connection_error=pool_err)
    authenticator = OdooAuthenticator(auth_config, mock_pool)
    with pytest.raises(NetworkError, match="Authentication failed: Timeout acquiring connection from pool."):
        await authenticator.authenticate("test_user", "test_key")

async def test_authenticate_pool_connection_error(auth_config):
    """Test authentication failure due to pool connection error."""
    pool_err = PoolConnectionError("Pool connection failed")
    mock_pool = MockPool(get_connection_error=pool_err)
    authenticator = OdooAuthenticator(auth_config, mock_pool)
    with pytest.raises(NetworkError, match="Authentication failed: Could not establish connection via pool."):
        await authenticator.authenticate("test_user", "test_key")

async def test_authenticate_missing_method_on_connection(auth_config):
    """Test failure if the connection object lacks the 'common.authenticate' method."""
    mock_pool = MockPool(missing_common=True)
    authenticator = OdooAuthenticator(auth_config, mock_pool)
    with pytest.raises(AuthError, match="Authentication mechanism not available via connection pool."):
        await authenticator.authenticate("test_user", "test_key")
