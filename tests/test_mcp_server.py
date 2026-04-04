import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odoo_mcp.core.mcp_server import OdooMCPServer
from odoo_mcp.error_handling.exceptions import ProtocolError


TEST_CONFIG = {
    "protocol": "xmlrpc",
    "connection_type": "stdio",
    "odoo_url": "http://test.odoo.com",
    "database": "test_db",
    "uid": "test_user",
    "password": "test_pass",
    "requests_per_minute": 120,
    "rate_limit_max_wait_seconds": 5,
    "pool_size": 5,
    "timeout": 30,
    "session_timeout_minutes": 60,
    "sse_queue_maxsize": 1000,
    "allowed_origins": ["*"],
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    },
}


@pytest_asyncio.fixture
async def server():
    instance = OdooMCPServer(TEST_CONFIG)
    yield instance
    await instance.stop()


@pytest.mark.asyncio
async def test_server_initialization():
    server = OdooMCPServer(TEST_CONFIG)
    assert server.protocol_type == "xmlrpc"
    assert server.connection_type == "stdio"
    assert server.rate_limiter.requests_per_minute == 120
    assert server.rate_limiter.max_wait_seconds == 5


@pytest.mark.asyncio
async def test_capabilities_advertise_resource_subscription(server):
    capabilities = server.capabilities_manager.get_capabilities()
    assert capabilities["resources"]["subscribe"] is True
    assert capabilities["resources"]["listChanged"] is True


@pytest.mark.asyncio
async def test_list_tools_exposes_current_public_names(server):
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert "odoo.search_read" in names
    assert "odoo.read" in names
    assert "odoo.create" in names
    assert "odoo.write" in names
    assert "odoo.actions.call" in names


@pytest.mark.asyncio
async def test_list_resources_includes_instance_info(server):
    resources = await server.list_resources()
    uris = {resource.uri for resource in resources}
    assert "odoo://instance/info" in uris
    assert "odoo://{model}/{id}" in uris
    assert "odoo://{model}/list" in uris
    assert "odoo://{model}/binary/{field}/{id}" in uris


@pytest.mark.asyncio
async def test_get_resource_odoo_instance_info(server):
    result = await server.get_resource("odoo://instance/info")
    assert result["uri"] == "odoo://instance/info"
    assert result["content"] == {
        "web_base_url": TEST_CONFIG["odoo_url"],
        "database_name": TEST_CONFIG["database"],
    }
    assert "password" not in result["content"]


@pytest.mark.asyncio
async def test_list_prompts_includes_registered_prompt_set(server):
    prompts = await server.list_prompts()
    names = {prompt.name for prompt in prompts}
    assert {
        "analyze-record",
        "create-record",
        "update-record",
        "advanced-search",
        "call-method",
    }.issubset(names)


@pytest.mark.asyncio
async def test_get_prompt_analyze_record_returns_analysis(server):
    server.pool.execute_kw = AsyncMock(
        side_effect=[
            [{"id": 7, "name": "Partner"}],
            {"name": {"type": "char"}},
        ]
    )

    result = await server.get_prompt("analyze-record", {"model": "res.partner", "id": 7})

    assert result["analysis"]["record"]["id"] == 7
    assert result["analysis"]["model"] == "res.partner"
    assert "fields_info" in result["analysis"]


@pytest.mark.asyncio
async def test_get_prompt_create_record_returns_prompt_context(server):
    server.pool.execute_kw = AsyncMock(
        return_value={
            "name": {"type": "char", "required": True},
            "email": {"type": "char", "required": False},
        }
    )

    result = await server.get_prompt(
        "create-record",
        {"model": "res.partner", "values": {"name": "Mario Rossi"}},
    )

    assert result["prompt"]["model"] == "res.partner"
    assert result["prompt"]["values"]["name"] == "Mario Rossi"
    assert "name" in result["prompt"]["required_fields"]


@pytest.mark.asyncio
async def test_get_prompt_supports_advanced_search_and_call_method(server):
    server.pool.execute_kw = AsyncMock(
        side_effect=[
            {"name": {"type": "char"}},
            {"method_name": {"method": True}},
        ]
    )

    search_prompt = await server.get_prompt(
        "advanced-search",
        {"model": "res.partner", "domain": [["name", "ilike", "Acme"]]},
    )
    call_prompt = await server.get_prompt(
        "call-method",
        {"model": "res.partner", "method": "search_read"},
    )

    assert search_prompt["prompt"]["model"] == "res.partner"
    assert search_prompt["prompt"]["domain"] == [["name", "ilike", "Acme"]]
    assert call_prompt["prompt"]["method"] == "search_read"
    assert "methods_info" in call_prompt["prompt"]


@pytest.mark.asyncio
async def test_get_prompt_unknown_raises_protocol_error(server):
    with pytest.raises(ProtocolError):
        await server.get_prompt("unknown-prompt", {})


@pytest.mark.asyncio
async def test_process_request_call_tool_search_read_returns_json_content(server):
    server.orm_tools.search_read = AsyncMock(return_value=[{"id": 1, "name": "Test Record"}])

    request = {
        "jsonrpc": "2.0",
        "method": "call_tool",
        "params": {
            "name": "odoo.search_read",
            "arguments": {
                "model": "res.partner",
                "domain_json": [["name", "=", "Test"]],
                "fields": ["id", "name"],
            },
        },
        "id": 1,
    }

    response = await server.process_request(request)

    assert response["jsonrpc"] == "2.0"
    assert "result" in response
    content = response["result"]["content"]
    assert len(content) == 1
    parsed = json.loads(content[0]["text"])
    assert parsed[0]["id"] == 1
    assert parsed[0]["name"] == "Test Record"
