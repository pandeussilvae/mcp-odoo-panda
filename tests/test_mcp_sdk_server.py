"""Tests for MCP SDK modern server (2026-07-28) + Tasks extension."""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from odoo_mcp.core.mcp_sdk_server import (
    PROTOCOL_VERSION,
    TASKS_EXTENSION_ID,
    build_asgi_app,
)


async def _echo_dispatch(name: str, arguments: dict, connection=None):
    return {"tool": name, "arguments": arguments, "connection": connection, "ok": True}


@pytest_asyncio.fixture
async def client():
    app = build_asgi_app(dispatch_tool=_echo_dispatch)
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


def _meta(*, with_tasks: bool = False) -> dict:
    caps: dict = {"extensions": {}}
    if with_tasks:
        caps["extensions"][TASKS_EXTENSION_ID] = {}
    return {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": caps,
        "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "0"},
    }


def _headers(method: str, name: str | None = None) -> dict:
    h = {
        "Content-Type": "application/json",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": method,
        "Accept": "application/json",
    }
    if name:
        h["Mcp-Name"] = name
    return h


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["protocolVersion"] == PROTOCOL_VERSION
    assert TASKS_EXTENSION_ID in data.get("extensions", [])


@pytest.mark.asyncio
async def test_discover(client):
    resp = await client.post(
        "/mcp",
        headers=_headers("server/discover"),
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": {"_meta": _meta()},
        },
    )
    assert resp.status_code == 200, resp.text
    result = resp.json().get("result") or {}
    caps = result.get("capabilities") or {}
    extensions = caps.get("extensions") or {}
    assert TASKS_EXTENSION_ID in extensions


@pytest.mark.asyncio
async def test_tools_list_and_call(client):
    resp = await client.post(
        "/mcp",
        headers=_headers("tools/list"),
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {"_meta": _meta()},
        },
    )
    assert resp.status_code == 200, resp.text
    tools = (resp.json().get("result") or {}).get("tools") or []
    names = [t.get("name") for t in tools]
    assert "odoo.search_read" in names

    resp = await client.post(
        "/mcp",
        headers=_headers("tools/call", "odoo.search_read"),
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "odoo.search_read",
                "arguments": {"model": "res.partner", "limit": 1},
                "_meta": _meta(),
            },
        },
    )
    assert resp.status_code == 200, resp.text
    result = resp.json().get("result") or {}
    assert result.get("isError") is False or result.get("is_error") is False
    sc = result.get("structuredContent") or result.get("structured_content") or {}
    assert sc.get("tool") == "odoo.search_read"


@pytest.mark.asyncio
async def test_initialize_returns_error(client):
    resp = await client.post(
        "/mcp",
        headers=_headers("initialize"),
        json={
            "jsonrpc": "2.0",
            "id": 9,
            "method": "initialize",
            "params": {"_meta": _meta()},
        },
    )
    body = resp.json()
    assert "error" in body or resp.status_code >= 400


@pytest.mark.asyncio
async def test_tasks_async_tool_and_get(client):
    meta = _meta(with_tasks=True)
    resp = await client.post(
        "/mcp",
        headers=_headers("tools/call", "odoo.search_read"),
        json={
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "odoo.search_read",
                "arguments": {"model": "res.partner", "async": True},
                "_meta": meta,
            },
        },
    )
    assert resp.status_code == 200, resp.text
    result = resp.json().get("result") or {}
    sc = result.get("structuredContent") or result.get("structured_content") or {}
    task_id = sc.get("taskId")
    assert task_id, sc

    status = "working"
    for _ in range(40):
        resp = await client.post(
            "/mcp",
            headers=_headers("tasks/get"),
            json={
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tasks/get",
                "params": {"taskId": task_id, "_meta": meta},
            },
        )
        assert resp.status_code == 200, resp.text
        tr = resp.json().get("result") or {}
        status = tr.get("status")
        if status in {"completed", "failed"}:
            break
        await asyncio.sleep(0.05)
    assert status == "completed"
