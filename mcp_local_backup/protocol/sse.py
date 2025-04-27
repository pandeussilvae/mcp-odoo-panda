"""
MCP (Model Context Protocol) SSE protocol implementation.
This module provides the Server-Sent Events (SSE) communication protocol for MCP.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, Callable, Set
from aiohttp import web
from aiohttp_sse import sse_response

logger = logging.getLogger(__name__)

class SSEProtocol:
    """
    Implements the MCP protocol over Server-Sent Events (SSE).
    Handles real-time communication with clients.
    """

    def __init__(
        self,
        request_handler: Callable[[Dict[str, Any]], Dict[str, Any]],
        allowed_origins: Optional[Set[str]] = None
    ):
        """
        Initialize the SSE protocol handler.

        Args:
            request_handler: Callback function to handle incoming requests
            allowed_origins: Set of allowed origins for CORS
        """
        self.request_handler = request_handler
        self.allowed_origins = allowed_origins or {"*"}
        self._running = False
        self._clients: Set[web.StreamResponse] = set()
        self._response_queue = asyncio.Queue()

    async def _sse_handler(self, request: web.Request) -> web.StreamResponse:
        """
        Handle SSE client connections.

        Args:
            request: The incoming HTTP request

        Returns:
            SSE response stream
        """
        # Check CORS
        origin = request.headers.get("Origin")
        if origin and "*" not in self.allowed_origins and origin not in self.allowed_origins:
            raise web.HTTPForbidden(reason="Origin not allowed")

        # Create SSE response
        response = await sse_response(request)
        self._clients.add(response)
        try:
            # Send initial connection message
            await response.send(json.dumps({
                "type": "connected",
                "data": {"message": "Connected to MCP server"}
            }))

            # Keep connection alive and send queued messages
            while not response.task.done():
                try:
                    message = await self._response_queue.get()
                    await response.send(json.dumps(message))
                except Exception as e:
                    logger.error(f"Error sending SSE message: {e}")
                    break

        finally:
            self._clients.remove(response)

    async def _post_handler(self, request: web.Request) -> web.Response:
        """
        Handle POST requests for MCP operations.

        Args:
            request: The incoming HTTP request

        Returns:
            HTTP response
        """
        try:
            # Parse request body
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError("Request must be a JSON object")

            # Handle the request
            response = self.request_handler(data)
            return web.json_response(response)

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in request: {e}")
            return web.json_response({
                "jsonrpc": "2.0",
                "error": {
                    "code": -32700,
                    "message": "Parse error"
                },
                "id": None
            }, status=400)

        except Exception as e:
            logger.error(f"Error handling request: {e}")
            return web.json_response({
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": "Internal error"
                },
                "id": None
            }, status=500)

    async def run(self, host: str = "localhost", port: int = 8080):
        """
        Run the SSE server.

        Args:
            host: Host to bind to
            port: Port to bind to
        """
        self._running = True
        app = web.Application()
        app.router.add_get("/events", self._sse_handler)
        app.router.add_post("/mcp", self._post_handler)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()

        logger.info(f"SSE server running at http://{host}:{port}")
        try:
            while self._running:
                await asyncio.sleep(1)
        finally:
            await runner.cleanup()
            self._running = False

    async def broadcast(self, message: Dict[str, Any]):
        """
        Broadcast a message to all connected clients.

        Args:
            message: The message to broadcast
        """
        await self._response_queue.put(message)

    def stop(self):
        """
        Stop the SSE server.
        """
        self._running = False 