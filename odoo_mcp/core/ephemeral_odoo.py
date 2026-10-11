"""Ephemeral Odoo JSON-RPC/XML-RPC calls for per-request connection overlay.

Standalone helper — accepts url/db/user/password dicts only (no Odward types).
TCP uses IP-pinned transport from ``safe_destination`` (anti-SSRF / DNS rebinding).
Optional ``connect_ip`` (from a trusted gateway) forces the dial address after
classification; otherwise the URL is validated and pinned locally.
"""

from __future__ import annotations

import asyncio
import xmlrpc.client
from typing import Any, Dict, List, Optional

from odoo_mcp.core.safe_destination import (
    DestinationPolicyError,
    open_xmlrpc_proxy,
    pin_from_url_and_ip,
    validate_odoo_destination,
)


def _xmlrpc_execute_kw(
    *,
    url: str,
    db: str,
    username: str,
    password: str,
    model: str,
    method: str,
    args: Optional[List[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
    connect_ip: Optional[str] = None,
) -> Any:
    if connect_ip:
        pinned = pin_from_url_and_ip(url, connect_ip)
    else:
        pinned = validate_odoo_destination(url)
    common = open_xmlrpc_proxy(url, "/xmlrpc/2/common", pinned=pinned)
    uid = common.authenticate(db, username, password, {})
    if not uid:
        raise PermissionError("Odoo authentication failed")
    models = open_xmlrpc_proxy(url, "/xmlrpc/2/object", pinned=pinned)
    return models.execute_kw(db, uid, password, model, method, args or [], kwargs or {})


async def ephemeral_execute_kw(
    conn: Dict[str, str],
    *,
    model: str,
    method: str,
    args: Optional[List[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
) -> Any:
    return await asyncio.to_thread(
        _xmlrpc_execute_kw,
        url=conn["url"],
        db=conn["db"],
        username=conn["username"],
        password=conn["password"],
        model=model,
        method=method,
        args=args,
        kwargs=kwargs,
        connect_ip=conn.get("connect_ip") or None,
    )


async def ephemeral_dispatch_tool(conn: Dict[str, str], name: str, arguments: Dict[str, Any]) -> Any:
    short = name[5:] if name.startswith("odoo.") else name
    model = str(arguments.get("model") or "").strip()
    if not model and short != "execute_kw":
        raise ValueError("model is required")

    if short == "search_read":
        domain = arguments.get("domain") or []
        if isinstance(domain, dict):
            # Accept domain_json style loosely
            domain = domain.get("domain") or []
        fields = arguments.get("fields")
        limit = int(arguments.get("limit") or 50)
        offset = int(arguments.get("offset") or 0)
        order = arguments.get("order")
        kwargs: Dict[str, Any] = {"limit": limit, "offset": offset}
        if fields is not None:
            kwargs["fields"] = fields
        if order:
            kwargs["order"] = order
        return await ephemeral_execute_kw(
            conn, model=model, method="search_read", args=[domain], kwargs=kwargs
        )
    if short == "read":
        ids = arguments.get("ids") or arguments.get("record_ids") or []
        fields = arguments.get("fields")
        kwargs = {"fields": fields} if fields is not None else {}
        return await ephemeral_execute_kw(conn, model=model, method="read", args=[ids], kwargs=kwargs)
    if short == "create":
        values = arguments.get("values") or {}
        return await ephemeral_execute_kw(conn, model=model, method="create", args=[values])
    if short == "write":
        ids = arguments.get("ids") or arguments.get("record_ids") or []
        values = arguments.get("values") or {}
        return await ephemeral_execute_kw(conn, model=model, method="write", args=[ids, values])
    if short == "unlink":
        ids = arguments.get("ids") or arguments.get("record_ids") or []
        return await ephemeral_execute_kw(conn, model=model, method="unlink", args=[ids])
    if short == "execute_kw":
        method = str(arguments.get("method") or "").strip()
        if not method:
            raise ValueError("method is required for execute_kw")
        return await ephemeral_execute_kw(
            conn,
            model=model,
            method=method,
            args=list(arguments.get("args") or []),
            kwargs=dict(arguments.get("kwargs") or {}),
        )
    if short == "fields_get":
        return await ephemeral_execute_kw(conn, model=model, method="fields_get", args=[])
    if short == "search_count":
        domain = arguments.get("domain") or []
        return await ephemeral_execute_kw(conn, model=model, method="search_count", args=[domain])
    raise ValueError(f"Unknown tool: {name}")
