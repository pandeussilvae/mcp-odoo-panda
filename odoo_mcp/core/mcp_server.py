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
# Remove the old placeholder validate_request_data if it exists in security.utils
from odoo_mcp.security.utils import RateLimiter, mask_sensitive_data
from odoo_mcp.error_handling.exceptions import OdooMCPError, ConfigurationError, ProtocolError, AuthError, NetworkError
from odoo_mcp.core.logging_config import setup_logging
# Import Pydantic validation components
from odoo_mcp.core.request_models import validate_request_params
from pydantic import ValidationError
# Import cache manager instance
from odoo_mcp.performance.caching import cache_manager, CACHE_TYPE

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
        # Initialize RateLimiter with max wait time from config
        self.rate_limiter = RateLimiter(
            requests_per_minute=config.get('requests_per_minute', 120),
            max_wait_seconds=config.get('rate_limit_max_wait_seconds', None) # Default to None (indefinite wait)
        )

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
        # Limit queue size to prevent excessive memory usage
        sse_queue_maxsize = config.get('sse_queue_maxsize', 1000) # Configurable max size
        self._sse_response_queue = asyncio.Queue(maxsize=sse_queue_maxsize)
        self._allowed_origins = config.get('allowed_origins', ['*']) # Store allowed origins

        logger.info(f"Server Configuration: Protocol={self.protocol_type}, PoolSize={self.pool.pool_size}, Timeout={self.pool.timeout}s")
        logger.info(f"Security: RateLimit={self.rate_limiter.rate}/min, TLS={config.get('tls_version', 'Default')}")


    async def handle_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single incoming JSON-RPC request dictionary.

        This method orchestrates the entire request lifecycle:
        1. Basic JSON-RPC structure validation.
        2. Rate limiting using the configured token bucket.
        3. Input parameter validation using Pydantic models defined in `request_models.py`.
        4. Dispatching the request to the appropriate internal handler method
           (e.g., `echo`, `create_session`, `call_odoo`).
        5. Handling potential errors (ProtocolError, AuthError, NetworkError, OdooMCPError,
           ValidationError) and formatting them into JSON-RPC error responses.

        Args:
            request_data: The parsed JSON-RPC request dictionary.

        Returns:
            A JSON-RPC response dictionary, containing either a 'result' or an 'error' field.
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
            raw_params = request_data.get("params", {})

            # 2. Rate Limiting
            # Acquire token, potentially waiting up to max_wait_seconds
            acquired = await self.rate_limiter.acquire()
            if not acquired:
                # If acquire returns False, it means it timed out waiting
                raise OdooMCPError("Rate limit exceeded and wait timed out. Please try again later.", code=-32000) # Custom error code

            # 3. Input Validation (using Pydantic)
            try:
                # Validate parameters based on the method
                # This raises ValidationError if inputs are invalid
                validated_params = validate_request_params(method, raw_params)
                logger.debug(f"Validated params for method '{method}': {validated_params.dict()}")
            except ValidationError as e:
                logger.warning(f"Invalid parameters for method '{method}': {e.errors()}")
                # Use JSON-RPC error code for invalid params
                raise ProtocolError(f"Invalid parameters: {e.errors()}", code=-32602)
            except KeyError:
                # Method exists in request but no validation model defined for it
                raise ProtocolError(f"Method not found or validation not defined: {method}", code=-32601)


            # 4. Method Dispatching (using validated_params)
            logger.info(f"Received request for method: {method}")
            if method == "echo":
                # Access validated data using attribute access
                response["result"] = validated_params.message
            elif method == "create_session":
                session = await self.session_manager.create_session(
                    username=validated_params.username,
                    api_key=validated_params.api_key
                )
                response["result"] = {"session_id": session.session_id, "user_id": session.user_id}
            elif method == "destroy_session":
                self.session_manager.destroy_session(validated_params.session_id)
                response["result"] = True # Indicate success
            elif method == "call_odoo":
                # Determine authentication: session or direct credentials from validated params
                auth_uid: Optional[int] = None
                auth_pwd: Optional[str] = None

                if validated_params.session_id:
                    session = self.session_manager.get_session(validated_params.session_id)
                    if not session:
                        raise AuthError(f"Invalid or expired session ID: {validated_params.session_id}")
                    auth_uid = session.user_id
                    logger.info(f"Using session {validated_params.session_id} for user {auth_uid}")
                    # WARNING: Current handler logic (especially XMLRPC) requires uid AND password for execute_kw.
                    # When using session_id, we are falling back to the global api_key/password from config.
                    # This might not be the desired behavior if the session implies a specific user's password/key.
                    # TODO: Refine session handling to securely associate/retrieve the correct password/key for the session's uid,
                    # or modify handlers if they can operate with uid only in a session context.
                    auth_pwd = self.config.get('api_key') or self.config.get('password') # Try both common names
                    if not auth_pwd:
                        logger.error("CRITICAL: Using session auth but NO global api_key/password found in config for handler's execute_kw call. This will likely fail.")
                        # Optionally, raise an error here if this fallback is unacceptable
                        # raise ConfigurationError("Global api_key/password required in config when using session_id with current handlers.")
                    else:
                        logger.warning("Using session ID for UID, but falling back to global api_key/password from config for handler's execute_kw call.")
                else:
                    # Use explicitly provided uid/password from validated params
                    auth_uid = validated_params.uid
                    auth_pwd = validated_params.password # Already validated that if one exists, the other does too

                # Get a connection and execute
                async with self.pool.get_connection() as wrapper:
                    handler_instance = wrapper.connection
                    result = handler_instance.execute_kw(
                        validated_params.model,
                        validated_params.method,
                        validated_params.args,
                        validated_params.kwargs,
                        uid=auth_uid,
                        password=auth_pwd
                    )
                    response["result"] = result
            # No 'else' needed here because validate_request_params already raised KeyError if method wasn't in map

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
        """
        Handle an incoming Server-Sent Events (SSE) connection request.

        Establishes an SSE connection using `aiohttp_sse.sse_response`, adds the
        client response object to a list of active clients, and continuously sends
        responses from the `_sse_response_queue` to this client until disconnection.

        Args:
            request: The incoming aiohttp.web.Request object.

        Returns:
            An aiohttp.web.StreamResponse object representing the SSE connection.
        """
        logger.info(f"SSE client connection attempt from: {request.remote}")
        resp: Optional[web.StreamResponse] = None # Initialize resp
        request_origin = request.headers.get('Origin')
        allowed = False
        cors_headers = {}

        # Improved CORS check
        if '*' in self._allowed_origins:
            allowed = True
            cors_headers['Access-Control-Allow-Origin'] = '*'
        elif request_origin and request_origin in self._allowed_origins:
            allowed = True
            cors_headers['Access-Control-Allow-Origin'] = request_origin
            # Allow credentials if specific origin is matched
            cors_headers['Access-Control-Allow-Credentials'] = 'true'
        else:
            logger.warning(f"SSE connection denied for origin: {request_origin}. Allowed: {self._allowed_origins}")
            # Return 403 Forbidden if origin not allowed
            return web.Response(status=403, text="Origin not allowed")

        # Add other common CORS headers if allowed
        if allowed:
             cors_headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
             cors_headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization' # Example headers

        try:
            # Prepare SSE response with dynamic CORS headers
            logger.info(f"SSE client allowed from origin: {request_origin or '*'}. Preparing response.")
            resp = await sse_response(request, headers=cors_headers)
            self._sse_clients.append(resp)
            await resp.prepare(request)
            logger.info(f"SSE client connected successfully: {request.remote}")

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
                      logger.info(f"SSE handler task cancelled for {request.remote}.")
                      break # Exit loop on cancellation
                 except Exception as e:
                      logger.exception(f"Error sending SSE event to {request.remote}: {e}. Removing client.")
                      # Assume persistent error, break loop to remove client in finally block
                      break # Exit loop on send error

        except Exception as e:
            # Catch errors during SSE connection setup or the send loop
            logger.exception(f"Error in SSE handler setup or main loop for {request.remote}: {e}")
        finally:
            # Ensure client is removed from the list upon disconnection or error
            logger.info(f"SSE client disconnected: {request.remote}")
            if resp and resp in self._sse_clients:
                self._sse_clients.remove(resp)
        # resp might be None if sse_response failed early
        return resp if resp else web.Response(status=500, text="Failed to establish SSE connection")


    async def _post_handler(self, request: web.Request) -> web.Response:
        """
        Handle incoming POST requests in SSE mode.

        Receives a JSON-RPC request via POST, processes it using `handle_request`,
        puts the resulting JSON-RPC response onto the `_sse_response_queue` for
        broadcasting via the `/events` endpoint, and returns a `202 Accepted` response.

        Args:
            request: The incoming aiohttp.web.Request object.

        Returns:
            An aiohttp.web.Response object (typically 202 Accepted or an error).
        """
        try:
            request_data = await request.json()
            masked_request_str = mask_sensitive_data(json.dumps(request_data), self.config)
            logger.info(f"Received POST request (masked): {masked_request_str}")

            # Handle request but put response onto SSE queue instead of returning directly
            response_data = await self.handle_request(request_data)

            # Put response onto the queue for SSE handler to send
            try:
                # Use put_nowait to avoid blocking if queue is full
                self._sse_response_queue.put_nowait(response_data)
                # Return simple acknowledgement
                return web.Response(status=202, text="Request accepted")
            except asyncio.QueueFull:
                logger.error(f"SSE response queue is full (maxsize={self._sse_response_queue.maxsize}). Discarding response for request ID {response_data.get('id')}.")
                # Return 503 Service Unavailable if queue is full
                return web.json_response(
                    {"jsonrpc": "2.0", "id": request_data.get("id"), "error": {"code": -32001, "message": "Server busy, SSE queue full. Please try again later."}},
                    status=503
                )

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
        """
        Signal handler to initiate graceful shutdown.

        Sets the global `shutdown_requested` flag upon receiving SIGINT or SIGTERM.
        This flag is checked by the main server loops (`_run_stdio_server`, `_run_sse_server`)
        to allow them to exit cleanly.

        Args:
            sig: The signal received (e.g., signal.SIGINT, signal.SIGTERM). Optional.
        """
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

    # Configure cache manager if cachetools is available
    if cache_manager and CACHE_TYPE == 'cachetools':
        try:
            cache_manager.configure(config)
        except Exception as e:
            logger.error(f"Failed to configure CacheManager: {e}", exc_info=True)
            # Decide if this is critical - maybe proceed without cache?
            # For now, log error and continue.

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
