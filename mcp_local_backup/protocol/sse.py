"""
MCP (Model Context Protocol) SSE protocol implementation.
This module provides the Server-Sent Events (SSE) communication protocol for MCP.
"""

import asyncio
import json
import logging
import uuid
import time
import sys
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
        print("[SSE] Inizializzazione protocollo SSE", file=sys.stderr)
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
        print(f"[SSE] Configurazione: timeout={self._client_timeout_seconds}s, heartbeat={self._heartbeat_interval}s", file=sys.stderr)

    async def _heartbeat_loop(self):
        while self._running:
            await asyncio.sleep(self._heartbeat_interval)
            print(f"[SSE] Invio heartbeat a {len(self._client_queues)} clients", file=sys.stderr)
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
        print(f"[SSE] Nuova richiesta di connessione da origin: {origin}", file=sys.stderr)
        if origin and "*" not in self.allowed_origins and origin not in self.allowed_origins:
            print(f"[SSE] Origin non permesso: {origin}", file=sys.stderr)
            raise web.HTTPForbidden(reason="Origin not allowed")

        # Create SSE response
        response = await sse_response(request)
        client_id = str(uuid.uuid4())  # Genera un client_id unico
        self._clients.add(response)
        self._client_queues[client_id] = asyncio.Queue()
        self._client_id_map[response] = client_id
        self._client_last_active[client_id] = time.time()
        print(f"[SSE] Nuovo client connesso: client_id={client_id}, totale clients: {len(self._clients)}", file=sys.stderr)
        try:
            # Invia evento di benvenuto con client_id e capabilities
            print(f"[SSE] Ricevuta richiesta da client: {request.headers}", file=sys.stderr)
            print(f"[SSE] Query params: {request.query_string}", file=sys.stderr)
            welcome_msg = {
                "jsonrpc": "2.0",
                "id": 0,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "MCP Odoo Server",
                        "version": "1.0.0"
                    }
                }
            }
            print(f"[SSE] Invio messaggio di benvenuto a {client_id}: {welcome_msg}", file=sys.stderr)
            await response.send(json.dumps(welcome_msg))
            
            # Invia anche il client_id come messaggio separato
            client_info = {
                "type": "connected",
                "data": {
                    "message": "Connected to MCP server",
                    "client_id": client_id
                }
            }
            await response.send(json.dumps(client_info))
            
            while not response.task.done():
                try:
                    # Timeout: se inattivo troppo a lungo, chiudi la connessione
                    now = time.time()
                    last_active = self._client_last_active[client_id]
                    inactive_time = now - last_active
                    if inactive_time > self._client_timeout_seconds:
                        print(f"[SSE] Timeout client_id={client_id}, inattivo da {inactive_time:.1f}s", file=sys.stderr)
                        break
                    try:
                        message = await asyncio.wait_for(self._client_queues[client_id].get(), timeout=5)
                    except asyncio.TimeoutError:
                        continue
                    if message is None:
                        # Heartbeat: invia commento SSE
                        print(f"[SSE] Heartbeat inviato a client_id={client_id}", file=sys.stderr)
                        await response.write(b': ping\n\n')
                        await response.drain()
                        continue
                    print(f"[SSE] Invio messaggio a client_id={client_id}: {message}", file=sys.stderr)
                    await response.send(json.dumps(message))
                    self._client_last_active[client_id] = time.time()
                except Exception as e:
                    print(f"[SSE] Errore nell'invio del messaggio a {client_id}: {e}", file=sys.stderr)
                    break
        finally:
            self._clients.remove(response)
            del self._client_queues[client_id]
            del self._client_id_map[response]
            del self._client_last_active[client_id]
            print(f"[SSE] Client disconnesso: client_id={client_id}, rimasti {len(self._clients)} clients", file=sys.stderr)
        return response

    async def _post_handler(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            print(f"[SSE] Ricevuto messaggio POST: {data}", file=sys.stderr)
            if isinstance(data, list):
                print(f"[SSE] Processando batch di {len(data)} messaggi", file=sys.stderr)
                for msg in data:
                    await self._process_single_message(msg)
            elif isinstance(data, dict):
                print("[SSE] Processando singolo messaggio", file=sys.stderr)
                await self._process_single_message(data)
            else:
                print(f"[SSE] Payload non valido: {data}", file=sys.stderr)
                return web.Response(status=400, text="Invalid JSON-RPC payload")
            return web.Response(status=202, text="Accepted")
        except Exception as e:
            print(f"[SSE] Errore nella gestione della richiesta POST: {e}", file=sys.stderr)
            return web.Response(status=500, text="Internal error")

    async def _process_single_message(self, msg: dict):
        """
        Processa un singolo messaggio JSON-RPC (richiesta o notifica) e invia la risposta/notifica via SSE.
        """
        try:
            client_id = msg.get("client_id")
            print(f"[SSE] Processando messaggio per client_id={client_id}: {msg}", file=sys.stderr)
            
            if not client_id or client_id not in self._client_queues:
                print(f"[SSE] Client ID non valido o non trovato: {client_id}", file=sys.stderr)
                return
                
            # Gestione cancellazione richieste
            if msg.get("method") == "cancel_request":
                cancelled_id = msg.get("params", {}).get("id")
                if cancelled_id:
                    self._cancelled_requests.add(cancelled_id)
                    print(f"[SSE] Richiesta cancellata: id={cancelled_id}", file=sys.stderr)
                return
                
            # Se la richiesta è stata cancellata, non processarla
            if msg.get("id") in self._cancelled_requests:
                print(f"[SSE] Ignoro richiesta cancellata: id={msg.get('id')}", file=sys.stderr)
                return
                
            print(f"[SSE] Chiamata handler per messaggio: {msg}", file=sys.stderr)
            response = self.request_handler(msg)
            print(f"[SSE] Risposta dall'handler: {response}", file=sys.stderr)
            
            if "id" in msg or (isinstance(response, dict) and ("result" in response or "error" in response)):
                print(f"[SSE] Accodo risposta per client {client_id}: {response}", file=sys.stderr)
                await self._client_queues[client_id].put(response)
            self._client_last_active[client_id] = time.time()
            
        except Exception as e:
            print(f"[SSE] Errore nel processare il messaggio: {e}", file=sys.stderr)
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
                print(f"[SSE] Invio risposta di errore a {client_id}: {error_response}", file=sys.stderr)
                await self._client_queues[client_id].put(error_response)

    async def run(self, host: str = "localhost", port: int = 8080):
        """
        Run the SSE server.

        Args:
            host: Host to bind to
            port: Port to bind to
        """
        print(f"[SSE] Avvio server su http://{host}:{port}", file=sys.stderr)
        self._running = True
        app = web.Application()
        app.router.add_get("/sse", self._sse_handler)
        app.router.add_post("/messages", self._post_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        print(f"[SSE] Server in ascolto su http://{host}:{port}", file=sys.stderr)
        # Avvia heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        try:
            while self._running:
                await asyncio.sleep(1)
        finally:
            print("[SSE] Arresto server in corso...", file=sys.stderr)
            await runner.cleanup()
            self._running = False
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
            print("[SSE] Server arrestato", file=sys.stderr)

    async def broadcast(self, message: Dict[str, Any]):
        """
        Invia un messaggio a tutti i client connessi (es. notifiche broadcast).
        """
        print(f"[SSE] Broadcasting messaggio a {len(self._client_queues)} clients: {message}", file=sys.stderr)

    def stop(self):
        """
        Stop the SSE server.
        """
        self._running = False 