"""
MCP (Model Context Protocol) SSE protocol implementation.
This module provides the Server-Sent Events (SSE) communication protocol for MCP.
"""

import asyncio
import json
import logging
import uuid
import time
from typing import Dict, Any, Optional, Callable, Set
from aiohttp import web
from aiohttp_sse import sse_response
import threading

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
        self._client_queues: Dict[str, asyncio.Queue] = {}
        self._client_id_map: Dict[web.StreamResponse, str] = {}
        self._client_last_active: Dict[str, float] = {}  # Per timeout
        self._client_timeout_seconds = 600  # 10 minuti di inattività
        self._heartbeat_interval = 30  # seconds
        self._heartbeat_task = None
        self._cancelled_requests = set()  # Track cancelled request ids

    async def _heartbeat_loop(self):
        while self._running:
            await asyncio.sleep(self._heartbeat_interval)
            for client_id, queue in self._client_queues.items():
                # Invia un commento SSE (ping)
                await queue.put(None)  # None indica heartbeat

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
        client_id = str(uuid.uuid4())  # Genera un client_id unico
        self._clients.add(response)
        self._client_queues[client_id] = asyncio.Queue()
        self._client_id_map[response] = client_id
        self._client_last_active[client_id] = time.time()
        logger.info(f"[SSE] Nuovo client connesso: client_id={client_id}")
        try:
            # Invia evento di benvenuto con client_id
            await response.send(json.dumps({
                "type": "connected",
                "data": {"message": "Connected to MCP server", "client_id": client_id}
            }))
            while not response.task.done():
                try:
                    # Timeout: se inattivo troppo a lungo, chiudi la connessione
                    now = time.time()
                    if now - self._client_last_active[client_id] > self._client_timeout_seconds:
                        logger.info(f"[SSE] Timeout client_id={client_id}, chiudo la connessione.")
                        break
                    try:
                        message = await asyncio.wait_for(self._client_queues[client_id].get(), timeout=5)
                    except asyncio.TimeoutError:
                        continue
                    if message is None:
                        # Heartbeat: invia commento SSE
                        await response.write(b': ping\n\n')
                        await response.drain()
                        continue
                    await response.send(json.dumps(message))
                    self._client_last_active[client_id] = time.time()
                except Exception as e:
                    logger.error(f"Error sending SSE message: {e}")
                    break
        finally:
            self._clients.remove(response)
            del self._client_queues[client_id]
            del self._client_id_map[response]
            del self._client_last_active[client_id]
            logger.info(f"[SSE] Client disconnesso: client_id={client_id}")

    async def _post_handler(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            logger.info(f"[SSE] Ricevuto messaggio POST: {data}")
            if isinstance(data, list):
                for msg in data:
                    await self._process_single_message(msg)
            elif isinstance(data, dict):
                await self._process_single_message(data)
            else:
                logger.error("Payload non valido: deve essere oggetto o array JSON-RPC")
                return web.Response(status=400, text="Invalid JSON-RPC payload")
            return web.Response(status=202, text="Accepted")
        except Exception as e:
            logger.error(f"Error handling request: {e}")
            return web.Response(status=500, text="Internal error")

    async def _process_single_message(self, msg: dict):
        """
        Processa un singolo messaggio JSON-RPC (richiesta o notifica) e invia la risposta/notifica via SSE.
        """
        try:
            client_id = msg.get("client_id")
            if not client_id or client_id not in self._client_queues:
                logger.error(f"Missing or invalid client_id in message: {client_id}")
                return
            # Gestione cancellazione richieste
            if msg.get("method") == "cancel_request":
                cancelled_id = msg.get("params", {}).get("id")
                if cancelled_id:
                    self._cancelled_requests.add(cancelled_id)
                    logger.info(f"[SSE] Richiesta cancellata: id={cancelled_id}")
                return
            # Se la richiesta è stata cancellata, non processarla
            if msg.get("id") in self._cancelled_requests:
                logger.info(f"[SSE] Ignoro richiesta cancellata: id={msg.get('id')}")
                return
            response = self.request_handler(msg)
            if "id" in msg or (isinstance(response, dict) and ("result" in response or "error" in response)):
                await self._client_queues[client_id].put(response)
            self._client_last_active[client_id] = time.time()
        except Exception as e:
            logger.error(f"Error processing single message: {e}")
            # Risposta di errore JSON-RPC standard
            error_response = {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
            if client_id and client_id in self._client_queues:
                await self._client_queues[client_id].put(error_response)

    async def run(self, host: str = "localhost", port: int = 8080):
        """
        Run the SSE server.

        Args:
            host: Host to bind to
            port: Port to bind to
        """
        self._running = True
        app = web.Application()
        app.router.add_get("/sse", self._sse_handler)
        app.router.add_post("/messages", self._post_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        logger.info(f"SSE server running at http://{host}:{port}")
        # Avvia heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        try:
            while self._running:
                await asyncio.sleep(1)
        finally:
            await runner.cleanup()
            self._running = False
            if self._heartbeat_task:
                self._heartbeat_task.cancel()

    async def broadcast(self, message: Dict[str, Any]):
        """
        Invia un messaggio a tutti i client connessi (es. notifiche broadcast).
        """
        for queue in self._client_queues.values():
            await queue.put(message)

    def stop(self):
        """
        Stop the SSE server.
        """
        self._running = False 