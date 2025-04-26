import pytest
import json
import asyncio
from typing import Dict, Any
from unittest.mock import Mock, patch, AsyncMock

from odoo_mcp.core.mcp_server import OdooMCPServer
from odoo_mcp.error_handling.exceptions import (
    OdooMCPError, ConfigurationError, ProtocolError, AuthError, NetworkError
)

# Test configuration
TEST_CONFIG = {
    "protocol": "xmlrpc",
    "connection_type": "stdio",
    "odoo_url": "http://test.odoo.com",
    "database": "test_db",
    "username": "test_user",
    "password": "test_pass",
    "requests_per_minute": 120,
    "rate_limit_max_wait_seconds": 5,
    "pool_size": 5,
    "timeout": 30,
    "session_timeout_minutes": 60,
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    }
}

@pytest.fixture
async def server():
    """Create a test server instance."""
    server = OdooMCPServer(TEST_CONFIG)
    yield server
    await server.shutdown()

@pytest.fixture
def mock_pool():
    """Create a mock connection pool."""
    pool = AsyncMock()
    pool.get_connection.return_value.__aenter__.return_value.connection = AsyncMock()
    return pool

@pytest.fixture
def mock_session_manager():
    """Create a mock session manager."""
    manager = AsyncMock()
    manager.get_session.return_value = Mock(user_id=1)
    return manager

@pytest.mark.asyncio
async def test_server_initialization():
    """Test server initialization."""
    server = OdooMCPServer(TEST_CONFIG)
    assert server.protocol_type == "xmlrpc"
    assert server.connection_type == "stdio"
    assert server.rate_limiter.rate == 120
    assert server.rate_limiter.max_wait_seconds == 5

@pytest.mark.asyncio
async def test_list_tools(server):
    """Test list_tools method."""
    tools = await server.list_tools()
    assert len(tools) > 0
    assert any(tool.name == "odoo_search_read" for tool in tools)
    assert any(tool.name == "odoo_read" for tool in tools)
    assert any(tool.name == "odoo_create" for tool in tools)
    assert any(tool.name == "odoo_write" for tool in tools)
    assert any(tool.name == "odoo_unlink" for tool in tools)
    assert any(tool.name == "odoo_call_method" for tool in tools)

@pytest.mark.asyncio
async def test_list_resources(server):
    """Test list_resources method."""
    resources = await server.list_resources()
    assert len(resources) > 0
    assert any(resource.uri == "odoo://{model}/{id}" for resource in resources)
    assert any(resource.uri == "odoo://{model}/list" for resource in resources)
    assert any(resource.uri == "odoo://{model}/binary/{field}/{id}" for resource in resources)

@pytest.mark.asyncio
async def test_list_prompts(server):
    """Test list_prompts method."""
    prompts = await server.list_prompts()
    assert len(prompts) > 0
    assert any(prompt.name == "analyze-record" for prompt in prompts)
    assert any(prompt.name == "create-record" for prompt in prompts)
    assert any(prompt.name == "update-record" for prompt in prompts)
    assert any(prompt.name == "advanced-search" for prompt in prompts)
    assert any(prompt.name == "call-method" for prompt in prompts)

@pytest.mark.asyncio
async def test_read_resource(server, mock_pool):
    """Test read_resource method."""
    server.pool = mock_pool
    mock_pool.get_connection.return_value.__aenter__.return_value.connection.execute_kw.return_value = [
        {"id": 1, "name": "Test Record"}
    ]

    result = await server.read_resource("odoo://res.partner/1")
    assert "contents" in result
    assert len(result["contents"]) == 1
    assert result["contents"][0]["uri"] == "odoo://res.partner/1"
    assert result["contents"][0]["mimeType"] == "application/json"

@pytest.mark.asyncio
async def test_read_resource_not_found(server, mock_pool):
    """Test read_resource with non-existent record."""
    server.pool = mock_pool
    mock_pool.get_connection.return_value.__aenter__.return_value.connection.execute_kw.return_value = []

    with pytest.raises(OdooMCPError):
        await server.read_resource("odoo://res.partner/999")

@pytest.mark.asyncio
async def test_read_binary_resource(server, mock_pool):
    """Test reading binary resource."""
    server.pool = mock_pool
    mock_pool.get_connection.return_value.__aenter__.return_value.connection.execute_kw.return_value = [
        {"image": "base64_encoded_data"}
    ]

    result = await server.read_resource("odoo://res.partner/binary/image/1")
    assert "contents" in result
    assert len(result["contents"]) == 1
    assert result["contents"][0]["uri"] == "odoo://res.partner/binary/image/1"
    assert result["contents"][0]["mimeType"] == "application/octet-stream"

@pytest.mark.asyncio
async def test_call_tool_search_read(server, mock_pool):
    """Test odoo_search_read tool."""
    server.pool = mock_pool
    mock_pool.get_connection.return_value.__aenter__.return_value.connection.execute_kw.return_value = [
        {"id": 1, "name": "Test Record"}
    ]

    result = await server.call_tool("odoo_search_read", {
        "model": "res.partner",
        "domain": [["name", "=", "Test"]],
        "fields": ["id", "name"]
    })
    assert "content" in result
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"

@pytest.mark.asyncio
async def test_call_tool_create(server, mock_pool):
    """Test odoo_create tool."""
    server.pool = mock_pool
    mock_pool.get_connection.return_value.__aenter__.return_value.connection.execute_kw.return_value = 1

    result = await server.call_tool("odoo_create", {
        "model": "res.partner",
        "values": {"name": "Test Partner"}
    })
    assert "content" in result
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"

@pytest.mark.asyncio
async def test_get_prompt_analyze_record(server):
    """Test analyze-record prompt."""
    result = await server.get_prompt("analyze-record", {"uri": "odoo://res.partner/1"})
    assert "messages" in result
    assert len(result["messages"]) == 1
    assert result["messages"][0]["role"] == "user"
    assert "content" in result["messages"][0]

@pytest.mark.asyncio
async def test_get_prompt_create_record(server):
    """Test create-record prompt."""
    result = await server.get_prompt("create-record", {"model": "res.partner"})
    assert "messages" in result
    assert len(result["messages"]) == 1
    assert result["messages"][0]["role"] == "user"
    assert "content" in result["messages"][0]

@pytest.mark.asyncio
async def test_sse_handler(server):
    """Test SSE handler."""
    if not hasattr(server, '_sse_handler'):
        pytest.skip("SSE support not available")

    mock_request = AsyncMock()
    mock_request.headers = {"Origin": "http://localhost"}
    mock_request.remote = "127.0.0.1"

    response = await server._sse_handler(mock_request)
    assert response is not None
    assert response.status == 200

@pytest.mark.asyncio
async def test_post_handler(server):
    """Test POST handler."""
    if not hasattr(server, '_post_handler'):
        pytest.skip("SSE support not available")

    mock_request = AsyncMock()
    mock_request.json.return_value = {
        "jsonrpc": "2.0",
        "method": "list_tools",
        "id": 1
    }

    response = await server._post_handler(mock_request)
    assert response.status == 202

@pytest.mark.asyncio
async def test_resource_subscription(server):
    """Test resource subscription."""
    await server.subscribe_resource("odoo://res.partner/1")
    # TODO: Add assertions once real-time updates are implemented

@pytest.mark.asyncio
async def test_resource_unsubscription(server):
    """Test resource unsubscription."""
    await server.unsubscribe_resource("odoo://res.partner/1")
    # TODO: Add assertions once real-time updates are implemented

@pytest.mark.asyncio
async def test_error_handling(server):
    """Test error handling."""
    with pytest.raises(ProtocolError):
        await server.read_resource("invalid://uri")

    with pytest.raises(ProtocolError):
        await server.call_tool("unknown_tool", {})

    with pytest.raises(ProtocolError):
        await server.get_prompt("unknown_prompt", {})

@pytest.mark.asyncio
async def test_shutdown(server):
    """Test server shutdown."""
    await server.shutdown()
    # TODO: Add assertions to verify cleanup

if __name__ == "__main__":
    pytest.main([__file__]) 