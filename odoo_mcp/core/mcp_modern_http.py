"""
MCP Streamable HTTP — protocol 2026-07-28 (modern-only).

Standalone Odoo MCP wire: POST /mcp only, no initialize/session.
Wraps ORMTools; no Odward imports (see ODWARD_BOUNDARY.md).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from aiohttp import web

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2026-07-28"
SERVER_NAME = "odoo-mcp-server"
SERVER_VERSION = "2026.9.3"

# Optional per-request connection overlay (standalone; no Odward types).
HEADER_ODOO_URL = "X-Odoo-Url"
HEADER_ODOO_DB = "X-Odoo-Db"
HEADER_ODOO_USER = "X-Odoo-User"
HEADER_ODOO_PASSWORD = "X-Odoo-Password"

ToolDispatcher = Callable[[str, Dict[str, Any]], Awaitable[Any]]
# Extended dispatcher may receive connection overlay as third arg.
ToolDispatcherWithConn = Callable[
    [str, Dict[str, Any], Optional[Dict[str, str]]],
    Awaitable[Any],
]


def _json_response(payload: Dict[str, Any], status: int = 200) -> web.Response:
    return web.json_response(payload, status=status)


def _require_protocol_header(request: web.Request) -> Optional[web.Response]:
    version = (request.headers.get("MCP-Protocol-Version") or "").strip()
    if not version:
        return _json_response(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32000,
                    "message": "Missing MCP-Protocol-Version header",
                    "data": {"expected": PROTOCOL_VERSION},
                },
            },
            status=400,
        )
    if version != PROTOCOL_VERSION:
        return _json_response(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32000,
                    "message": "Unsupported protocol version",
                    "data": {"got": version, "expected": PROTOCOL_VERSION},
                },
            },
            status=406,
        )
    return None


def _meta_ok(params: Dict[str, Any]) -> Optional[str]:
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        return "params._meta is required"
    pv = str(
        meta.get("io.modelcontextprotocol/protocolVersion")
        or meta.get("protocolVersion")
        or ""
    ).strip()
    if pv and pv != PROTOCOL_VERSION:
        return f"params._meta protocolVersion must be {PROTOCOL_VERSION}"
    return None


def _tool_catalog() -> List[Dict[str, Any]]:
    """Static catalog mirroring ORM tools registered by OdooMCPServer."""
    return [
        {
            "name": "odoo.search_read",
            "description": "Search and read Odoo records",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "domain": {"type": "array"},
                    "fields": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                    "order": {"type": "string"},
                },
                "required": ["model"],
            },
        },
        {
            "name": "odoo.read",
            "description": "Read Odoo records by ids",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "ids": {"type": "array", "items": {"type": "integer"}},
                    "fields": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["model", "ids"],
            },
        },
        {
            "name": "odoo.create",
            "description": "Create an Odoo record",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "values": {"type": "object"},
                },
                "required": ["model", "values"],
            },
        },
        {
            "name": "odoo.write",
            "description": "Update Odoo records",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "ids": {"type": "array", "items": {"type": "integer"}},
                    "values": {"type": "object"},
                },
                "required": ["model", "ids", "values"],
            },
        },
        {
            "name": "odoo.unlink",
            "description": "Delete Odoo records",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["model", "ids"],
            },
        },
        {
            "name": "odoo.execute_kw",
            "description": "Call an arbitrary Odoo model method via execute_kw",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "method": {"type": "string"},
                    "args": {"type": "array"},
                    "kwargs": {"type": "object"},
                },
                "required": ["model", "method"],
            },
        },
    ]


def _call_tool_result(payload: Any, *, is_error: bool = False) -> Dict[str, Any]:
    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, default=str)
        structured = payload if isinstance(payload, dict) else {"items": payload}
    else:
        text = str(payload)
        structured = {"output": text}
    return {
        "resultType": "complete",
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
        "isError": bool(is_error),
    }


def _connection_from_request(request: web.Request, params: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Extract optional connection-config from headers or params (no secrets logged)."""
    cc = params.get("connection") if isinstance(params.get("connection"), dict) else {}
    url = (
        (request.headers.get(HEADER_ODOO_URL) or "").strip()
        or str(cc.get("url") or cc.get("odoo_url") or "").strip()
    )
    db = (
        (request.headers.get(HEADER_ODOO_DB) or "").strip()
        or str(cc.get("db") or cc.get("database") or "").strip()
    )
    user = (
        (request.headers.get(HEADER_ODOO_USER) or "").strip()
        or str(cc.get("username") or cc.get("user") or "").strip()
    )
    password = (
        (request.headers.get(HEADER_ODOO_PASSWORD) or "").strip()
        or str(cc.get("password") or cc.get("api_key") or "").strip()
    )
    if not (url and db and user and password):
        return None
    return {"url": url, "db": db, "username": user, "password": password}


class ModernMcpHttpApp:
    """aiohttp application for MCP 2026-07-28 POST /mcp."""

    def __init__(
        self,
        *,
        dispatch_tool: Any,
        config: Optional[Dict[str, Any]] = None,
        tool_catalog: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.dispatch_tool = dispatch_tool
        self.config = config or {}
        self.tool_catalog = tool_catalog or _tool_catalog()
        self.app = web.Application()
        self.app.router.add_get("/health", self._health)
        self.app.router.add_get("/healthz", self._health)
        self.app.router.add_post("/mcp", self._handle_mcp)
        self.app.router.add_options("/mcp", self._options)

    async def _health(self, _request: web.Request) -> web.Response:
        return _json_response(
            {
                "ok": True,
                "protocolVersion": PROTOCOL_VERSION,
                "server": SERVER_NAME,
                "version": SERVER_VERSION,
            }
        )

    async def _options(self, _request: web.Request) -> web.Response:
        return web.Response(
            status=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": (
                    "Content-Type, Authorization, MCP-Protocol-Version, Mcp-Method, Mcp-Name"
                ),
            },
        )

    async def _handle_mcp(self, request: web.Request) -> web.Response:
        header_err = _require_protocol_header(request)
        if header_err is not None:
            return header_err

        try:
            body = await request.json()
        except Exception:
            return _json_response(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                },
                status=400,
            )

        if not isinstance(body, dict):
            return _json_response(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                },
                status=400,
            )

        req_id = body.get("id")
        method = str(body.get("method") or "").strip()
        # Prefer body method; allow Mcp-Method header as mirror.
        header_method = (request.headers.get("Mcp-Method") or "").strip()
        if header_method and method and header_method != method:
            return _json_response(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32020,
                        "message": "HeaderMismatch",
                        "data": {"reason": "Mcp-Method does not match body.method"},
                    },
                },
                status=400,
            )
        if not method and header_method:
            method = header_method

        # Reject legacy initialize — modern-only (before _meta validation).
        if method in {"initialize", "notifications/initialized"}:
            return _json_response(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": "initialize is not supported (modern-only 2026-07-28)",
                    },
                },
                status=400,
            )

        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        meta_err = _meta_ok(params)
        if meta_err and method not in {"server/discover"}:
            return _json_response(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": meta_err},
                },
                status=400,
            )

        try:
            if method == "server/discover":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False},
                    },
                    "ttlMs": 60_000,
                }
            elif method in {"tools/list", "list_tools"}:
                result = {"tools": self.tool_catalog}
            elif method in {"tools/call", "call_tool"}:
                name = str(params.get("name") or request.headers.get("Mcp-Name") or "").strip()
                arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
                if not name:
                    return _json_response(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {"code": -32602, "message": "tools/call requires name"},
                        },
                        status=400,
                    )
                conn = _connection_from_request(request, params)
                try:
                    import inspect

                    if len(inspect.signature(self.dispatch_tool).parameters) >= 3:
                        tool_out = await self.dispatch_tool(name, arguments, conn)
                    else:
                        tool_out = await self.dispatch_tool(name, arguments)
                    result = _call_tool_result(tool_out, is_error=False)
                except Exception as exc:
                    logger.exception("tools/call failed: %s", name)
                    result = _call_tool_result(
                        {
                            "success": False,
                            "message": str(exc),
                            "error": type(exc).__name__,
                        },
                        is_error=True,
                    )
            else:
                return _json_response(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"Method not found: {method}"},
                    },
                    status=404,
                )
        except Exception as exc:
            logger.exception("MCP request failed")
            return _json_response(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": type(exc).__name__, "data": str(exc)},
                },
                status=500,
            )

        return _json_response({"jsonrpc": "2.0", "id": req_id, "result": result})


async def dispatch_orm_tool(
    orm_tools: Any,
    name: str,
    arguments: Dict[str, Any],
    connection: Optional[Dict[str, str]] = None,
) -> Any:
    """Map MCP tool names to ORMTools methods (or ephemeral conn overlay)."""
    if connection:
        from .ephemeral_odoo import ephemeral_dispatch_tool

        return await ephemeral_dispatch_tool(connection, name, arguments)

    short = name
    if short.startswith("odoo."):
        short = short[len("odoo.") :]

    mapping = {
        "search_read": "search_read",
        "read": "read",
        "create": "create",
        "write": "write",
        "unlink": "unlink",
        "execute_kw": "execute_kw",
        "fields_get": "fields_get",
        "search_count": "search_count",
    }
    method_name = mapping.get(short) or mapping.get(name)
    if not method_name or not hasattr(orm_tools, method_name):
        raise ValueError(f"Unknown tool: {name}")

    kwargs = dict(arguments or {})
    # Normalize common aliases from MCP clients
    if "ids" in kwargs and "record_ids" not in kwargs:
        kwargs["record_ids"] = kwargs.pop("ids")
    if "domain" in kwargs and "domain_json" not in kwargs and not isinstance(kwargs.get("domain"), dict):
        # ORMTools expects domain_json; pass list domain as-is when method accepts domain
        pass
    if "user_id" not in kwargs:
        try:
            kwargs["user_id"] = await orm_tools._get_global_uid()
        except Exception:
            kwargs["user_id"] = 1

    method = getattr(orm_tools, method_name)
    return await method(**kwargs)


async def run_modern_http_server(
    *,
    orm_tools: Any,
    config: Dict[str, Any],
    tool_catalog: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Run aiohttp site until cancelled."""

    async def _dispatch(name: str, arguments: Dict[str, Any]) -> Any:
        return await dispatch_orm_tool(orm_tools, name, arguments)

    modern = ModernMcpHttpApp(
        dispatch_tool=_dispatch,
        config=config,
        tool_catalog=tool_catalog,
    )
    host = config.get("http", {}).get("host", "0.0.0.0")
    port = int(config.get("http", {}).get("port", 8080))
    runner = web.AppRunner(modern.app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("MCP 2026-07-28 HTTP server started on %s:%s (POST /mcp)", host, port)
    import asyncio

    while True:
        await asyncio.sleep(3600)
