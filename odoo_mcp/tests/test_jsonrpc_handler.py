import asyncio
import pytest
import respx # For mocking httpx requests
import httpx
import ssl
from unittest.mock import patch

# Import the class to test and related exceptions
from odoo_mcp.core.jsonrpc_handler import JSONRPCHandler
from odoo_mcp.error_handling.exceptions import NetworkError, ProtocolError, ConfigurationError, AuthError

# Mark all tests in this module as asyncio
pytestmark = pytest.mark.asyncio

# --- Test Fixtures ---

@pytest.fixture
def jsonrpc_config():
    """Provides a default config for JSONRPCHandler tests."""
    return {
        'odoo_url': 'http://mock-odoo:8069', # Use http for simpler tests first
        'database': 'mock_db',
        'timeout': 10,
        # Add other relevant keys if needed
    }

@pytest.fixture
def jsonrpc_config_https():
    """Provides a config with HTTPS URL."""
    return {
        'odoo_url': 'https://mock-odoo:8069',
        'database': 'mock_db',
        'timeout': 10,
        'tls_version': 'TLSv1.3', # Example TLS setting
    }

# --- Test Cases ---

# Initialization Tests
async def test_handler_initialization_http(jsonrpc_config):
    """Test successful initialization with HTTP URL."""
    handler = JSONRPCHandler(jsonrpc_config)
    assert isinstance(handler.async_client, httpx.AsyncClient)
    assert handler.jsonrpc_url == "http://mock-odoo:8069/jsonrpc"
    assert handler.async_client.timeout.read == 10.0
    # Default verify should be True for httpx client
    assert isinstance(handler.async_client.verify, bool) and handler.async_client.verify is True
    await handler.close() # Close the client

async def test_handler_initialization_https_defaults(jsonrpc_config_https):
    """Test successful initialization with HTTPS URL and default TLS."""
    handler = JSONRPCHandler(jsonrpc_config_https)
    assert isinstance(handler.async_client, httpx.AsyncClient)
    assert handler.jsonrpc_url == "https://mock-odoo:8069/jsonrpc"
    # Verify should be an SSLContext when TLS is configured
    assert isinstance(handler.async_client.verify, ssl.SSLContext)
    await handler.close()

async def test_handler_initialization_https_custom_ca(jsonrpc_config_https):
    """Test initialization with HTTPS and custom CA."""
    jsonrpc_config_https['ca_cert_path'] = "/fake/ca.pem"
    handler = JSONRPCHandler(jsonrpc_config_https)
    assert isinstance(handler.async_client.verify, ssl.SSLContext)
    # Note: httpx uses the context for verification, not the direct path string like requests
    # We can't easily assert the CA path was loaded without deeper inspection/mocking of ssl.SSLContext
    await handler.close()

async def test_handler_initialization_https_client_cert(jsonrpc_config_https):
    """Test initialization with HTTPS and client cert."""
    jsonrpc_config_https['client_cert_path'] = "/fake/client.crt"
    jsonrpc_config_https['client_key_path'] = "/fake/client.key"
    handler = JSONRPCHandler(jsonrpc_config_https)
    assert handler.async_client.cert == ("/fake/client.crt", "/fake/client.key")
    await handler.close()

# Call Tests (using respx for mocking)

@respx.mock
async def test_call_direct_success(jsonrpc_config):
    """Test a successful direct JSON-RPC call."""
    handler = JSONRPCHandler(jsonrpc_config)
    url = handler.jsonrpc_url
    expected_payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "object",
            "method": "execute_kw",
            "args": [handler.database, 1, "password", "res.partner", "read", [[1], ["name"]]]
        },
        "id": None
    }
    mock_response_data = {"jsonrpc": "2.0", "id": None, "result": [{"id": 1, "name": "Test Partner"}]}

    # Mock the specific POST request
    respx.post(url).mock(return_value=httpx.Response(200, json=mock_response_data))

    # Make the call
    result = await handler.call("object", "execute_kw", [1, "password", "res.partner", "read", [[1], ["name"]]])

    # Assertions
    assert result == [{"id": 1, "name": "Test Partner"}]
    # Check that the request was made
    assert respx.calls.call_count == 1
    called_request = respx.calls.last.request
    assert called_request.method == "POST"
    assert str(called_request.url) == url
    # Compare JSON payload carefully
    sent_payload = json.loads(called_request.content)
    assert sent_payload == expected_payload

    await handler.close()

# TODO: Add more tests:
# - test_call_direct_http_error (4xx, 5xx)
# - test_call_direct_jsonrpc_error
# - test_call_direct_network_error (timeout, connect error)
# - test_call_direct_invalid_json_response
# - test_call_cached_success (requires patching cache decorator or installing cachetools)
# - test_call_no_cache_if_disabled
