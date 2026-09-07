"""Unit tests for MCP 2026-07-28 modern HTTP transport."""

from __future__ import annotations

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from odoo_mcp.core.mcp_modern_http import PROTOCOL_VERSION, ModernMcpHttpApp


async def _echo_tool(name: str, arguments: dict):
    return {"tool": name, "arguments": arguments, "ok": True}


@pytest_asyncio.fixture
async def client():
    app_wrapper = ModernMcpHttpApp(dispatch_tool=_echo_tool)
    server = TestServer(app_wrapper.app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["protocolVersion"] == PROTOCOL_VERSION


@pytest.mark.asyncio
async def test_discover_requires_protocol_header(client):
    resp = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {}},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_discover_and_tools_list(client):
    headers = {"MCP-Protocol-Version": PROTOCOL_VERSION, "Mcp-Method": "server/discover"}
    resp = await client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION}},
        },
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["result"]["protocolVersion"] == PROTOCOL_VERSION

    headers = {"MCP-Protocol-Version": PROTOCOL_VERSION, "Mcp-Method": "tools/list"}
    resp = await client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION}},
        },
    )
    assert resp.status == 200
    tools = (await resp.json())["result"]["tools"]
    assert any(t["name"] == "odoo.search_read" for t in tools)


@pytest.mark.asyncio
async def test_tools_call(client):
    headers = {
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": "tools/call",
        "Mcp-Name": "odoo.search_read",
    }
    resp = await client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "odoo.search_read",
                "arguments": {"model": "res.partner", "limit": 1},
                "_meta": {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION},
            },
        },
    )
    assert resp.status == 200
    result = (await resp.json())["result"]
    assert result["resultType"] == "complete"
    assert result["isError"] is False
    assert result["structuredContent"]["tool"] == "odoo.search_read"


@pytest.mark.asyncio
async def test_initialize_rejected(client):
    headers = {"MCP-Protocol-Version": PROTOCOL_VERSION}
    resp = await client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 9, "method": "initialize", "params": {}},
    )
    assert resp.status == 400
    err = (await resp.json())["error"]
    assert "initialize" in err["message"].lower() or "modern-only" in err["message"].lower()
