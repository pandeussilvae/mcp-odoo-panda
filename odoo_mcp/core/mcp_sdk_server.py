"""MCP 2026-07-28 server built on the official Python SDK (mcp>=2.1.1).

Modern-only Streamable HTTP (stateless JSON). No Odward imports.
Optional per-request Odoo connection via X-Odoo-* headers.
Optional Tasks extension (io.modelcontextprotocol/tasks) — minimal in-process
implementation until SDK ships SEP-2663 (#2806).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from mcp.server import Server
from mcp.server.context import ServerRequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    RequestParams,
    Result,
    TextContent,
    Tool,
)
from mcp_types.version import LATEST_MODERN_VERSION
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from .ephemeral_odoo import ephemeral_dispatch_tool

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = LATEST_MODERN_VERSION  # 2026-07-28
SERVER_NAME = "odoo-mcp-server"
SERVER_VERSION = "2026.9.7"

HEADER_ODOO_URL = "X-Odoo-Url"
HEADER_ODOO_DB = "X-Odoo-Db"
HEADER_ODOO_USER = "X-Odoo-User"
HEADER_ODOO_PASSWORD = "X-Odoo-Password"

TASKS_EXTENSION_ID = "io.modelcontextprotocol/tasks"

_connection_ctx: ContextVar[Optional[Dict[str, str]]] = ContextVar(
    "odoo_mcp_connection", default=None
)

ToolDispatch = Callable[
    [str, Dict[str, Any], Optional[Dict[str, str]]],
    Awaitable[Any],
]


def connection_from_headers(headers: Any) -> Optional[Dict[str, str]]:
    get = headers.get if hasattr(headers, "get") else lambda _k, d=None: d
    url = str(get(HEADER_ODOO_URL) or get(HEADER_ODOO_URL.lower()) or "").strip()
    db = str(get(HEADER_ODOO_DB) or get(HEADER_ODOO_DB.lower()) or "").strip()
    user = str(get(HEADER_ODOO_USER) or get(HEADER_ODOO_USER.lower()) or "").strip()
    password = str(
        get(HEADER_ODOO_PASSWORD) or get(HEADER_ODOO_PASSWORD.lower()) or ""
    ).strip()
    if not (url and db and user and password):
        return None
    return {"url": url, "db": db, "username": user, "password": password}


def get_request_connection() -> Optional[Dict[str, str]]:
    return _connection_ctx.get()


class OdooConnectionMiddleware(BaseHTTPMiddleware):
    """Capture X-Odoo-* into a ContextVar for the request lifetime."""

    async def dispatch(self, request: Request, call_next):
        conn = connection_from_headers(request.headers)
        token = _connection_ctx.set(conn)
        try:
            return await call_next(request)
        finally:
            _connection_ctx.reset(token)


def _tool_catalog() -> List[Tool]:
    def schema(props: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
        return {"type": "object", "properties": props, "required": required}

    return [
        Tool(
            name="odoo.search_read",
            description="Search and read Odoo records",
            input_schema=schema(
                {
                    "model": {"type": "string"},
                    "domain": {"type": "array"},
                    "fields": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                    "order": {"type": "string"},
                    "async": {
                        "type": "boolean",
                        "description": "If true and client opted into tasks, return a task handle",
                    },
                },
                ["model"],
            ),
        ),
        Tool(
            name="odoo.read",
            description="Read Odoo records by ids",
            input_schema=schema(
                {
                    "model": {"type": "string"},
                    "ids": {"type": "array", "items": {"type": "integer"}},
                    "fields": {"type": "array", "items": {"type": "string"}},
                },
                ["model", "ids"],
            ),
        ),
        Tool(
            name="odoo.create",
            description="Create an Odoo record",
            input_schema=schema(
                {"model": {"type": "string"}, "values": {"type": "object"}},
                ["model", "values"],
            ),
        ),
        Tool(
            name="odoo.write",
            description="Update Odoo records",
            input_schema=schema(
                {
                    "model": {"type": "string"},
                    "ids": {"type": "array", "items": {"type": "integer"}},
                    "values": {"type": "object"},
                },
                ["model", "ids", "values"],
            ),
        ),
        Tool(
            name="odoo.unlink",
            description="Delete Odoo records",
            input_schema=schema(
                {
                    "model": {"type": "string"},
                    "ids": {"type": "array", "items": {"type": "integer"}},
                },
                ["model", "ids"],
            ),
        ),
        Tool(
            name="odoo.execute_kw",
            description="Call an arbitrary Odoo model method via execute_kw",
            input_schema=schema(
                {
                    "model": {"type": "string"},
                    "method": {"type": "string"},
                    "args": {"type": "array"},
                    "kwargs": {"type": "object"},
                    "async": {"type": "boolean"},
                },
                ["model", "method"],
            ),
        ),
        Tool(
            name="odoo.fields_get",
            description="Introspect Odoo model fields",
            input_schema=schema({"model": {"type": "string"}}, ["model"]),
        ),
        Tool(
            name="odoo.search_count",
            description="Count Odoo records matching a domain",
            input_schema=schema(
                {"model": {"type": "string"}, "domain": {"type": "array"}},
                ["model"],
            ),
        ),
    ]


@dataclass
class _TaskRecord:
    task_id: str
    status: str = "working"  # working | completed | failed | cancelled
    created_at: float = field(default_factory=time.time)
    result: Any = None
    error: Optional[str] = None


_TASKS: Dict[str, _TaskRecord] = {}
_TASKS_LOCK = asyncio.Lock()


class TaskGetParams(RequestParams):
    taskId: str = Field(alias="taskId")

    model_config = {"populate_by_name": True}


class TaskCancelParams(RequestParams):
    taskId: str = Field(alias="taskId")

    model_config = {"populate_by_name": True}


class TaskGetResult(Result):
    taskId: str
    status: str
    result: Any = None
    error: Optional[str] = None


class TaskCancelResult(Result):
    taskId: str
    status: str


def _client_opted_into_tasks(ctx: ServerRequestContext) -> bool:
    """True when client declared Tasks (extension id and/or capabilities.tasks)."""
    meta = ctx.meta
    if meta is None:
        return False
    raw: dict[str, Any]
    if isinstance(meta, dict):
        raw = meta
    else:
        try:
            if hasattr(meta, "model_dump"):
                dumped = meta.model_dump(by_alias=True, exclude_none=True)
                raw = dumped if isinstance(dumped, dict) else {}
            else:
                raw = dict(meta)  # type: ignore[arg-type]
        except Exception:
            return False
    caps = (
        raw.get("io.modelcontextprotocol/clientCapabilities")
        or raw.get("clientCapabilities")
        or {}
    )
    if not isinstance(caps, dict):
        return False
    extensions = caps.get("extensions") or {}
    if isinstance(extensions, dict) and TASKS_EXTENSION_ID in extensions:
        return True
    # MCP 2.1 also models tasks as a first-class client capability
    return caps.get("tasks") is not None


def _call_tool_result(payload: Any, *, is_error: bool = False) -> CallToolResult:
    if isinstance(payload, (dict, list)):
        import json

        text = json.dumps(payload, default=str)
        structured = payload if isinstance(payload, dict) else {"items": payload}
    else:
        text = str(payload)
        structured = {"output": text}
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=structured,
        is_error=bool(is_error),
    )


def build_sdk_server(
    *,
    dispatch_tool: ToolDispatch,
    server_name: str = SERVER_NAME,
    server_version: str = SERVER_VERSION,
) -> Server:
    """Build low-level SDK Server with ORM tools + Tasks methods."""

    async def on_list_tools(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        return ListToolsResult(tools=_tool_catalog())

    async def on_call_tool(
        ctx: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult:
        name = str(params.name or "").strip()
        arguments = dict(params.arguments or {})
        want_async = bool(arguments.pop("async", False))
        conn = get_request_connection()

        if want_async and _client_opted_into_tasks(ctx):
            task_id = secrets.token_urlsafe(12)
            rec = _TaskRecord(task_id=task_id, status="working")
            async with _TASKS_LOCK:
                _TASKS[task_id] = rec

            async def _run() -> None:
                try:
                    out = await dispatch_tool(name, arguments, conn)
                    async with _TASKS_LOCK:
                        rec.status = "completed"
                        rec.result = out
                except Exception as exc:
                    logger.exception("background task failed: %s", task_id)
                    async with _TASKS_LOCK:
                        rec.status = "failed"
                        rec.error = f"{type(exc).__name__}: {exc}"

            asyncio.create_task(_run())
            return _call_tool_result(
                {
                    "taskId": task_id,
                    "status": "working",
                    "extension": TASKS_EXTENSION_ID,
                    "message": "Task accepted; poll with tasks/get",
                }
            )

        try:
            out = await dispatch_tool(name, arguments, conn)
            return _call_tool_result(out, is_error=False)
        except Exception as exc:
            logger.exception("tools/call failed: %s", name)
            return _call_tool_result(
                {"success": False, "message": str(exc), "error": type(exc).__name__},
                is_error=True,
            )

    async def handle_tasks_get(
        ctx: ServerRequestContext, params: TaskGetParams
    ) -> TaskGetResult:
        if not _client_opted_into_tasks(ctx):
            # Spec: revert or reject — we reject when method used without opt-in
            raise ValueError(f"Client must opt into {TASKS_EXTENSION_ID}")
        async with _TASKS_LOCK:
            rec = _TASKS.get(params.taskId)
        if rec is None:
            raise ValueError(f"Unknown taskId: {params.taskId}")
        return TaskGetResult(
            taskId=rec.task_id,
            status=rec.status,
            result=rec.result,
            error=rec.error,
        )

    async def handle_tasks_cancel(
        ctx: ServerRequestContext, params: TaskCancelParams
    ) -> TaskCancelResult:
        if not _client_opted_into_tasks(ctx):
            raise ValueError(f"Client must opt into {TASKS_EXTENSION_ID}")
        async with _TASKS_LOCK:
            rec = _TASKS.get(params.taskId)
            if rec is None:
                raise ValueError(f"Unknown taskId: {params.taskId}")
            if rec.status == "working":
                rec.status = "cancelled"
        return TaskCancelResult(taskId=params.taskId, status=rec.status)

    server = Server(
        server_name,
        version=server_version,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
    # Advertise Tasks extension (opt-in for clients).
    server.extensions[TASKS_EXTENSION_ID] = {
        "cancel": True,
        "list": False,
        "createViaToolAsyncFlag": True,
    }
    server.add_request_handler("tasks/get", TaskGetParams, handle_tasks_get)
    server.add_request_handler("tasks/cancel", TaskCancelParams, handle_tasks_cancel)
    return server


def build_asgi_app(
    *,
    dispatch_tool: ToolDispatch,
    host: str = "0.0.0.0",
) -> ASGIApp:
    server = build_sdk_server(dispatch_tool=dispatch_tool)
    starlette_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host=host,
    )
    # Prepend connection middleware
    starlette_app.add_middleware(OdooConnectionMiddleware)

    # Health endpoints used by compose healthcheck
    async def health(_request: Request) -> Response:
        import json

        body = json.dumps(
            {
                "ok": True,
                "protocolVersion": PROTOCOL_VERSION,
                "server": SERVER_NAME,
                "version": SERVER_VERSION,
                "extensions": list(server.extensions.keys()),
            }
        )
        return Response(body, media_type="application/json")

    starlette_app.routes.insert(
        0,
        __import__("starlette.routing", fromlist=["Route"]).Route(
            "/health", health, methods=["GET"]
        ),
    )
    starlette_app.routes.insert(
        0,
        __import__("starlette.routing", fromlist=["Route"]).Route(
            "/healthz", health, methods=["GET"]
        ),
    )
    return starlette_app


async def run_sdk_http_server(
    *,
    dispatch_tool: ToolDispatch,
    host: str = "0.0.0.0",
    port: int = 8080,
) -> None:
    import uvicorn

    app = build_asgi_app(dispatch_tool=dispatch_tool, host=host)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    logger.info(
        "MCP SDK modern HTTP listening on %s:%s (POST /mcp, protocol %s)",
        host,
        port,
        PROTOCOL_VERSION,
    )
    await server.serve()


async def dispatch_orm_tool(
    orm_tools: Any,
    name: str,
    arguments: Dict[str, Any],
    connection: Optional[Dict[str, str]] = None,
) -> Any:
    """Shared dispatcher used by SDK server and tests."""
    if connection:
        return await ephemeral_dispatch_tool(connection, name, arguments)

    short = name[5:] if name.startswith("odoo.") else name
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
    method_name = mapping.get(short)
    if not method_name or not hasattr(orm_tools, method_name):
        raise ValueError(f"Unknown tool: {name}")

    kwargs = dict(arguments or {})
    if "ids" in kwargs and "record_ids" not in kwargs:
        kwargs["record_ids"] = kwargs.pop("ids")
    if "user_id" not in kwargs:
        try:
            kwargs["user_id"] = await orm_tools._get_global_uid()
        except Exception:
            kwargs["user_id"] = 1
    method = getattr(orm_tools, method_name)
    return await method(**kwargs)
