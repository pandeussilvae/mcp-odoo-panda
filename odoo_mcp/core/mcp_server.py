import asyncio
import sys
import json
import logging
import signal
from typing import Dict, Any, Optional, Type, Union, List
import yaml
from datetime import datetime

# Import core components
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler
from odoo_mcp.core.jsonrpc_handler import JSONRPCHandler
from odoo_mcp.connection.connection_pool import ConnectionPool
from odoo_mcp.authentication.authenticator import OdooAuthenticator
from odoo_mcp.connection.session_manager import SessionManager
from odoo_mcp.security.utils import RateLimiter, mask_sensitive_data, validate_request_data
from odoo_mcp.error_handling.exceptions import OdooMCPError, ConfigurationError, ProtocolError, AuthError, NetworkError
from odoo_mcp.core.logging_config import setup_logging

# Imports for SSE mode
try:
    from aiohttp import web
    from aiohttp_sse import sse_response
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

logger = logging.getLogger(__name__)

# Global flag to signal shutdown
shutdown_requested = False

class MCPServer:
    """
    Main MCP Server class orchestrating request handling, connection management,
    and communication modes (stdio, SSE).
    """
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the MCP Server.

        Args:
            config: The loaded server configuration dictionary.

        Raises:
            ConfigurationError: If essential configuration is missing or invalid.
        """
        self.config = config
        self.protocol_type = config.get('protocol', 'xmlrpc').lower()
        self.connection_type = config.get('connection_type', 'stdio').lower()
        self.rate_limiter = RateLimiter(config.get('requests_per_minute', 120))

        # Initialize core components
        self.handler: Union[XMLRPCHandler, JSONRPCHandler]
        HandlerClass: Union[Type[XMLRPCHandler], Type[JSONRPCHandler]]

        if self.protocol_type == 'xmlrpc':
            HandlerClass = XMLRPCHandler
        elif self.protocol_type == 'jsonrpc':
            HandlerClass = JSONRPCHandler
        else:
            raise ConfigurationError(f"Unsupported protocol type: {self.protocol_type}")

        # Connection Pool requires the handler class for creating connections
        self.pool = ConnectionPool(config, HandlerClass)
        # Authenticator uses the pool to make auth calls
        self.authenticator = OdooAuthenticator(config, self.pool)
        # Session Manager uses the authenticator
        self.session_manager = SessionManager(config, self.authenticator, self.pool)
        # The handler might need access to the pool or session manager later
        # For now, let's assume the handler is self-contained after init
        # self.handler = HandlerClass(config) # Pool creates handler instances

        # SSE specific state
        self._sse_clients: List[web.StreamResponse] = []
        self._sse_response_queue = asyncio.Queue() # Queue for responses to send via SSE

        logger.info(f"Server Configuration: Protocol={self.protocol_type}, PoolSize={self.pool.pool_size}, Timeout={self.pool.timeout}s")
        logger.info(f"Security: RateLimit={self.rate_limiter.rate}/min, TLS={config.get('tls_version', 'Default')}")


    async def handle_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handles an incoming JSON-RPC request dictionary.

        Performs validation, rate limiting, method dispatching, and error handling.

        Args:
            request_data: The parsed JSON-RPC request dictionary.

        Returns:
            A JSON-RPC response dictionary.
        """
        response: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_data.get("id", None) # Echo back ID if present
        }

        try:
            # 1. Basic Validation (JSON-RPC structure)
            if not all(k in request_data for k in ["jsonrpc", "method"]):
                raise ProtocolError("Invalid JSON-RPC request structure (missing 'jsonrpc' or 'method').")
            if request_data["jsonrpc"] != "2.0":
                raise ProtocolError("Unsupported JSON-RPC version.")

            method = request_data["method"]
            params = request_data.get("params", {})

            # 2. Rate Limiting
            if not self.rate_limiter.try_acquire():
                raise OdooMCPError("Rate limit exceeded. Please try again later.", code=-32000) # Custom error code

            # 3. Input Validation (using Pydantic if available)
            # Example: Validate params based on the method called
            # validate_request_data(method, params) # Implement this based on defined models

            # 4. Method Dispatching
            logger.info(f"Received request for method: {method}")
            if method == "echo":
                response["result"] = params.get("message", "echo!")
            elif method == "create_session":
                # Requires username/api_key in params
                session = await self.session_manager.create_session(
                    username=params.get("username"),
                    api_key=params.get("api_key")
                )
                response["result"] = {"session_id": session.session_id, "user_id": session.user_id}
            elif method == "destroy_session":
                session_id = params.get("session_id")
                if not session_id: raise ProtocolError("Missing 'session_id' parameter for destroy_session.")
                self.session_manager.destroy_session(session_id)
                response["result"] = True # Indicate success
            elif method == "call_odoo":
                # Requires model, method, args, potentially session_id or uid/password
                model = params.get("model")
                odoo_method = params.get("method")
                odoo_args = params.get("args", [])
                odoo_kwargs = params.get("kwargs", {})
                session_id = params.get("session_id")

                if not model or not odoo_method:
                    raise ProtocolError("Missing 'model' or 'method' parameter for call_odoo.")

                # Determine authentication: session or direct credentials
                auth_uid: Optional[int] = None
                auth_pwd: Optional[str] = None

                if session_id:
                    session = self.session_manager.get_session(session_id)
                    if not session:
                        raise AuthError(f"Invalid or expired session ID: {session_id}")
                    auth_uid = session.user_id
                    # We might need the original password/key if the handler requires it per call
                    # This highlights a design choice: does the handler use UID only, or UID+pwd?
                    # Assuming for now the handler can operate with just UID if needed,
                    # or Session stores necessary credentials (less secure).
                    # Let's assume execute_kw needs uid and password. How to get password from session?
                    # Option A: Session stores password (bad)
                    # Option B: Handler uses a global password associated with the UID (requires lookup)
                    # Option C: Authenticator provides a way to get password for UID (complex)
                    # Option D: Pass password along with session_id (bad)
                    # Let's stick to passing explicit uid/password for now if session_id isn't used,
                    # and assume session implies using global credentials for that user if needed by handler.
                    # This part needs refinement based on chosen auth flow.
                    # For now, if session_id is valid, we'll try using global creds implicitly in execute_kw.
                    logger.info(f"Using session {session_id} for user {auth_uid}")
                    # We still need the password for the execute_kw call in the handler currently
                    # Let's try fetching global password if session is used (simplification for now)
                    auth_pwd = self.config.get('api_key') # Fallback to global API key if using session
                    if not auth_pwd: logger.warning("Using session auth but no global API key found for handler call.")

                else:
                    # Allow explicit uid/password override if needed, otherwise handler uses global
                    auth_uid = params.get("uid")
                    auth_pwd = params.get("password") # Or api_key? Standardize param name
                    if auth_uid and not auth_pwd: raise ProtocolError("Parameter 'password' required if 'uid' is provided.")
                    if auth_pwd and not auth_uid: raise ProtocolError("Parameter 'uid' required if 'password' is provided.")

                # Get a connection and execute
                # The handler instance is created by the pool
                async with self.pool.get_connection() as wrapper:
                    handler_instance = wrapper.connection
                    # Pass explicit creds if provided, otherwise handler uses its internal logic (global creds)
                    result = handler_instance.execute_kw(
                        model, odoo_method, odoo_args, odoo_kwargs,
                        uid=auth_uid, password=auth_pwd
                    )
                    response["result"] = result
            else:
                raise ProtocolError(f"Method not found: {method}", code=-32601)

        except (ProtocolError, AuthError, NetworkError, ConfigurationError, OdooMCPError) as e:
            logger.warning(f"Error handling request: {e}", exc_info=True if isinstance(e, (NetworkError, OdooMCPError)) else False)
            response["error"] = e.to_jsonrpc_error()
        except Exception as e:
            logger.exception(f"Unexpected internal server error: {e}")
            # Generic internal error
            response["error"] = {"code": -32603, "message": "Internal server error", "data": str(e)}

        # Mask sensitive data in the response if necessary before returning/sending
        # (e.g., if result contains sensitive info and masking is configured)
        # masked_response = mask_sensitive_data(response, self.config)
        # return masked_response
        return response

    async def _run_stdio_server(self):
        """Run the server in stdio mode."""
        logger.info("Starting stdio server loop...")
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        writer_transport, writer_protocol = await asyncio.get_running_loop().connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, asyncio.get_running_loop())

        logger.info("Stdio pipes connected. Waiting for requests...")

        while not shutdown_requested:
            try:
                line = await reader.readline()
                if not line:
                    logger.info("EOF received, closing stdio server.")
                    break
                request_str = line.decode().strip()
                if not request_str:
                    continue

                logger.debug(f"Received raw request: {request_str}")
                masked_request_str = mask_sensitive_data(request_str, self.config)
                logger.info(f"Received request (masked): {masked_request_str}")

                try:
                    request_data = json.loads(request_str)
                except json.JSONDecodeError:
                    logger.warning("Failed to decode JSON request.")
                    error_resp = {
                        "jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "Parse error"}
                    }
                    response_str = json.dumps(error_resp) + '\n'
                    writer.write(response_str.encode())
                    await writer.drain()
                    continue

                # Handle the request asynchronously
                response_data = await self.handle_request(request_data)

                # Send response
                response_str = json.dumps(response_data) + '\n'
                masked_response_str = mask_sensitive_data(response_str.strip(), self.config)
                logger.info(f"Sending response (masked): {masked_response_str}")
                writer.write(response_str.encode())
                await writer.drain()

            except ConnectionResetError:
                 logger.info("Stdio connection reset.")
                 break
            except Exception as e:
                 logger.exception(f"Error in stdio server loop: {e}")
                 # Avoid crashing the loop on unexpected errors
                 await asyncio.sleep(1) # Prevent fast error loops

    async def _sse_handler(self, request: web.Request) -> web.StreamResponse:
        """Handles incoming SSE connections."""
        logger.info(f"SSE client connected: {request.remote}")
        try:
            resp = await sse_response(request, headers={
                'Access-Control-Allow-Origin': self.config.get('allowed_origins', ['*'])[0] # Basic CORS
            })
            self._sse_clients.append(resp)
            await resp.prepare(request)

            # Keep connection open, send responses from queue
            while not resp.task.done(): # Check if client disconnected
                 try:
                      response_data = await self._sse_response_queue.get()
                      response_str = json.dumps(response_data)
                      masked_response_str = mask_sensitive_data(response_str, self.config)
                      logger.info(f"Sending SSE event (masked): {masked_response_str}")
                      await resp.send(response_str)
                      self._sse_response_queue.task_done()
                 except asyncio.CancelledError:
                      logger.info("SSE handler task cancelled.")
                      break
                 except Exception as e:
                      logger.exception(f"Error sending SSE event: {e}")
                      # Continue loop even if one send fails?

        except Exception as e:
            logger.exception(f"Error in SSE handler setup or main loop: {e}")
        finally:
            logger.info(f"SSE client disconnected: {request.remote}")
            if resp in self._sse_clients:
                self._sse_clients.remove(resp)
        return resp

    async def _post_handler(self, request: web.Request) -> web.Response:
        """Handles incoming POST requests to trigger operations."""
        try:
            request_data = await request.json()
            masked_request_str = mask_sensitive_data(json.dumps(request_data), self.config)
            logger.info(f"Received POST request (masked): {masked_request_str}")

            # Handle request but put response onto SSE queue instead of returning directly
            response_data = await self.handle_request(request_data)

            # Put response onto the queue for SSE handler to send
            await self._sse_response_queue.put(response_data)

            # Return simple acknowledgement
            return web.Response(status=202, text="Request accepted")

        except json.JSONDecodeError:
            logger.warning("Failed to decode JSON POST request.")
            return web.json_response(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                status=400
            )
        except Exception as e:
            logger.exception(f"Error handling POST request: {e}")
            return web.json_response(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": "Internal server error"}},
                status=500
            )

    async def _run_sse_server(self):
        """Run the server in SSE mode using aiohttp."""
        if not AIOHTTP_AVAILABLE:
            logger.critical("aiohttp and/or aiohttp-sse not installed. Cannot run in SSE mode.")
            logger.critical("Install with: pip install aiohttp aiohttp-sse")
            return

        app = web.Application()
        app.router.add_get('/events', self._sse_handler) # SSE endpoint
        app.router.add_post('/mcp', self._post_handler) # Endpoint to submit requests

        host = self.config.get('host', 'localhost')
        port = self.config.get('port', 8080)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        logger.info(f"Starting SSE server on http://{host}:{port}")
        await site.start()

        # Keep server running until shutdown signal
        while not shutdown_requested:
            await asyncio.sleep(1)

        # Cleanup
        logger.info("Shutting down SSE server...")
        await runner.cleanup()
        logger.info("SSE server stopped.")


    async def run(self):
        """Start the MCP server and run the appropriate communication loop."""
        global shutdown_requested
        shutdown_requested = False
        loop = asyncio.get_running_loop()

        # Add signal handlers for graceful shutdown
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.request_shutdown, sig)

        logger.info("Starting Odoo MCP Server...")
        # Start background tasks
        await self.pool.start_health_checks()
        await self.session_manager.start_cleanup_task()

        try:
            if self.connection_type == 'stdio':
                await self._run_stdio_server()
            elif self.connection_type == 'sse':
                await self._run_sse_server()
            else:
                raise ConfigurationError(f"Unsupported connection_type: {self.connection_type}")
        finally:
            logger.info("Server run loop finished. Initiating final cleanup...")
            await self.shutdown() # Ensure cleanup happens even if loop exits unexpectedly

    def request_shutdown(self, sig: Optional[signal.Signals] = None):
        """Signal handler to initiate graceful shutdown."""
        global shutdown_requested
        if not shutdown_requested:
             signame = sig.name if sig else "signal"
             logger.info(f"Received {signame}, requesting shutdown...")
             shutdown_requested = True
        else:
             logger.warning("Shutdown already requested.")


    async def shutdown(self):
        """Perform graceful shutdown of server components."""
        logger.info("Starting graceful shutdown...")
        # Stop background tasks first
        await self.session_manager.stop_cleanup_task()
        # Close pool (cancels health checks and closes idle connections)
        await self.pool.close()
        # Close handlers (important for httpx client)
        # Need to iterate through active connections in pool? Pool close handles idle.
        # Handlers associated with active sessions might need explicit closing?
        # For now, assume pool closure is sufficient or handlers close on release.
        # If JSONRPCHandler was stored directly:
        if hasattr(self, 'handler') and hasattr(self.handler, 'close'):
             await self.handler.close() # Close handler if it has resources (like httpx client)
        elif self.protocol_type == 'jsonrpc':
             # If using pool, handlers are closed when connections are closed/released.
             # But the main handler instance might not be in the pool.
             # Let's assume the pool handles closing connections/handlers.
             pass

        logger.info("MCP Server shutdown complete.")


async def main(config_path: str = "odoo_mcp/config/config.dev.yaml"):
    """Main entry point to load config and run the server."""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        # Use basic console logging if config load fails
        logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
        logger.critical(f"Configuration file not found: {config_path}")
        return
    except yaml.YAMLError as e:
        logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
        logger.critical(f"Error parsing configuration file {config_path}: {e}")
        return

    # Setup logging based on the loaded configuration
    setup_logging(config)

    try:
        server = MCPServer(config)
        await server.run()
    except ConfigurationError as e:
         logger.critical(f"Server configuration error: {e}", exc_info=True)
    except Exception as e:
         logger.critical(f"Failed to start or run server: {e}", exc_info=True)

if __name__ == "__main__":
    # Example: Allow passing config path via command line argument
    import argparse
    parser = argparse.ArgumentParser(description="Odoo MCP Server")
    parser.add_argument(
        "-c", "--config",
        default="odoo_mcp/config/config.dev.yaml",
        help="Path to the configuration file (YAML format)."
    )
    args = parser.parse_args()

    try:
        asyncio.run(main(config_path=args.config))
    except KeyboardInterrupt:
        logger.info("Server stopped by user (KeyboardInterrupt).")
    finally:
         logger.info("Exiting application.")
