#!/usr/bin/env python3
"""Headers-only entrypoint: Streamable HTTP MCP without a static Odoo pool.

Every tools/call must carry X-Odoo-Url / X-Odoo-Db / X-Odoo-User / X-Odoo-Password
(injected by a gateway or client). Useful as a multi-tenant sidecar.
"""

from __future__ import annotations

import asyncio
import logging
import os

logging.basicConfig(level=os.getenv("LOGGING_LEVEL", "INFO"))
logger = logging.getLogger("panda-ephemeral")


async def main() -> None:
    from odoo_mcp.core.ephemeral_odoo import ephemeral_dispatch_tool
    from odoo_mcp.core.mcp_sdk_server import run_sdk_http_server

    host = os.getenv("PANDA_HTTP_HOST", "0.0.0.0")
    port = int(os.getenv("PANDA_HTTP_PORT", "8090"))

    async def dispatch(name: str, arguments: dict, connection: dict | None):
        if not connection:
            raise PermissionError(
                "Missing X-Odoo-* headers — gateway must inject per-request credentials"
            )
        return await ephemeral_dispatch_tool(connection, name, arguments)

    logger.info("Starting headers-only panda on %s:%s (POST /mcp)", host, port)
    await run_sdk_http_server(dispatch_tool=dispatch, host=host, port=port)


if __name__ == "__main__":
    asyncio.run(main())
