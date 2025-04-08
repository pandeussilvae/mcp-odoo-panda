import asyncio
import logging
from typing import Dict, Any, Optional, Type

# Import components
import json # Needed for json operations below
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler
from odoo_mcp.core.jsonrpc_handler import JSONRPCHandler
from odoo_mcp.connection.connection_pool import ConnectionPool
from odoo_mcp.connection.session_manager import SessionManager
from odoo_mcp.authentication.authenticator import OdooAuthenticator
from odoo_mcp.security.utils import RateLimiter, validate_request_data, mask_sensitive_data # Import validation and masking
from odoo_mcp.error_handling.exceptions import AuthError, ProtocolError, NetworkError, ConfigurationError, OdooMCPError
# Import Pydantic error if available for specific handling
try:
    from pydantic import ValidationError
except ImportError:
    ValidationError = ValueError # Fallback if Pydantic not installed

logger = logging.getLogger(__name__)

class MCPServer:
    """
    The main Odoo Message Control Program (MCP) Server application class.

    Orchestrates the initialization, startup, request handling, and shutdown
    of the server and its various components (connection pool, session manager,
    authenticator, protocol handlers, etc.) based on a provided configuration.
    Supports communication via stdio (JSON-RPC line-based) or SSE (TODO).
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the MCP Server and its components.

        Performs configuration validation and sets up core components like
        logging, rate limiting, connection pool, authentication, session management,
        and selects the appropriate Odoo communication handler (XMLRPC/JSONRPC).

        Args:
            config: A dictionary containing the server configuration, typically loaded
                    from a YAML file. Expected keys include:
                    'odoo_url', 'database', 'username', 'api_key' (required),
                    'pool_size', 'timeout', 'connection_type' ('stdio'/'sse'),
                    'protocol' ('xmlrpc'/'jsonrpc'), 'tls_version', 'retry_count',
                    'cache_timeout', 'requests_per_minute', 'log_level', etc.

        Raises:
            ConfigurationError: If essential configuration keys are missing or invalid,
                                or if component initialization fails due to config issues.
            OdooMCPError: For other unexpected errors during initialization.
        """
        self.config = config
        logger.info("Initializing Odoo MCP Server...")

        # --- Configuration Validation ---
        self.odoo_url = config.get('odoo_url')
        self.database = config.get('database')
        self.username = config.get('username')
        self.api_key = config.get('api_key')

        if not all([self.odoo_url, self.database, self.username, self.api_key]):
            raise ConfigurationError("Missing essential Odoo connection configuration (odoo_url, database, username, api_key).")

        # --- Core Components Initialization ---
        self.pool_size = config.get('pool_size', 10)
        self.timeout = config.get('timeout', 30)
        self.connection_type = config.get('connection_type', 'stdio') # stdio | sse
        self.protocol = config.get('protocol', 'xmlrpc').lower() # xmlrpc | jsonrpc
        self.tls_version = config.get('tls_version', 'TLSv1.3') # TODO: Enforce TLS version
        self.retry_count = config.get('retry_count', 3)
        self.cache_timeout = config.get('cache_timeout', 300) # TODO: Implement LRU Cache
        requests_per_min = config.get('requests_per_minute', 60) # Default 60 req/min

        logger.info(f"Server Configuration: Protocol={self.protocol}, PoolSize={self.pool_size}, Timeout={self.timeout}s")
        logger.info(f"Security: RateLimit={requests_per_min}/min, TLS={self.tls_version}")

        # TODO: Add TLS context configuration based on self.tls_version for handlers

        # --- Security Components ---
        self.rate_limiter = RateLimiter(requests_per_minute=requests_per_min)

        # --- Connection and Session Management ---
        # Determine handler class based on config
        if self.protocol == 'jsonrpc':
            handler_class = JSONRPCHandler
            logger.info("Using JSONRPCHandler.")
        elif self.protocol == 'xmlrpc':
            handler_class = XMLRPCHandler
            logger.info("Using XMLRPCHandler.")
        else:
            raise ConfigurationError(f"Unsupported protocol specified: {self.protocol}. Use 'xmlrpc' or 'jsonrpc'.")

        try:
            self.connection_pool = ConnectionPool(config, handler_class)
            self.authenticator = OdooAuthenticator(config, self.connection_pool)
            self.session_manager = SessionManager(config, self.authenticator, self.connection_pool)
        except OdooMCPError as e:
             logger.exception(f"Failed to initialize core components: {e}")
             raise ConfigurationError(f"Error during component initialization: {e}", original_exception=e)
        except Exception as e:
             logger.exception(f"Unexpected error during server initialization: {e}")
             raise OdooMCPError(f"Unexpected error during server initialization: {e}", original_exception=e)


        self._running = False # Flag indicating if the server is actively running
        self._server_task: Optional[asyncio.Task] = None # Task running the main server loop (stdio/sse)

    async def start(self):
        """
        Start the MCP server.

        Initializes background tasks (connection pool health checks, session cleanup)
        and starts the main server communication loop (stdio or sse) based on config.
        """
        if self._running:
            logger.warning("Server start requested, but it is already running.")
            return

        logger.info("Starting Odoo MCP Server...")
        self._running = True

        # Start background tasks
        await self.connection_pool.start_health_checks()

        # Start session cleanup task
        await self.session_manager.start_cleanup_task()

        # Start the actual server listener (stdio or sse)
        if self.connection_type == 'stdio':
            logger.info("Starting server listener in stdio mode.")
            self._server_task = asyncio.create_task(self._run_stdio_server())
        elif self.connection_type == 'sse':
            logger.info("Starting server in SSE mode.")
            # self._server_task = asyncio.create_task(self._run_sse_server())
            pass # Placeholder
        else:
            logger.error(f"Unsupported connection type: {self.connection_type}")
            self._running = False
            # No need to close pool here as it wasn't fully started in error case
            return

        logger.info(f"Odoo MCP Server started successfully in {self.connection_type} mode.")
        # Note: The main execution loop (`main` function) will typically keep the
        # process alive while the server task runs. This start() method initiates
        # the tasks but doesn't necessarily block indefinitely itself.
        # Error handling for the server task failing might be needed in `main`.
        # Example:
        # if self._server_task:
        #     try:
        #         await self._server_task
        #     except asyncio.CancelledError:
        #         logger.info("Server task cancelled.")
        #     except Exception as e:
        #         logger.exception(f"Server task failed: {e}")
        #         await self.stop() # Stop everything if server task fails


    async def stop(self):
        """
        Stop the MCP server gracefully.

        Cancels background tasks (server listener, session cleanup, health checks via pool.close)
        and closes the connection pool.
        """
        if not self._running:
            logger.warning("Server stop requested, but it is not running.")
            return

        logger.info("Stopping Odoo MCP Server...")
        self._running = False

        # Stop the server listener task
        if self._server_task and not self._server_task.done():
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                logger.info("Server listener task successfully cancelled.")
            except Exception as e:
                 logger.exception(f"Error waiting for server listener task cancellation: {e}")


        # Stop session cleanup task
        await self.session_manager.stop_cleanup_task()

        # Close the connection pool (stops health checks and closes connections)
        await self.connection_pool.close()

        logger.info("Odoo MCP Server stopped.")

    # --- Server Communication Logic ---

    async def _run_stdio_server(self):
        """
        Run the main server loop for stdio communication.

        Reads JSON requests line-by-line from stdin, parses them, handles them
        concurrently using `handle_request`, and writes JSON responses to stdout.
        """
        logger.info("Starting stdio server loop...")
        loop = asyncio.get_running_loop()
        # Use sys import
        import sys
        import json # Import json here

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        # Check if stdin is connected (might fail in some environments)
        try:
             stdin_transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        except (OSError, RuntimeError) as e:
             logger.critical(f"Failed to connect to stdin: {e}. Stdio mode requires a connected stdin pipe.")
             self._running = False # Stop server if stdin fails
             return


        writer_transport, writer_protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, loop)

        logger.info("Stdio pipes connected. Waiting for requests...")

        try:
            while self._running:
                # Read line by line, assuming one JSON object per line.
                try:
                    line = await reader.readline()
                    if not line:
                        logger.info("EOF received on stdin, stopping server.")
                        break # End of input

                    request_str = line.decode('utf-8').strip()
                    if not request_str:
                        continue # Skip empty lines

                    logger.debug(f"Received raw request line: {request_str}")

                    # Parse JSON request
                    try:
                        request_data = json.loads(request_str)
                        if not isinstance(request_data, dict):
                             raise ValueError("Request must be a JSON object.")
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to decode JSON request: {e}")
                        error_response = {"jsonrpc": "2.0", "error": {"code": -32700, "message": f"Parse error: {e}"}, "id": None}
                        await self._write_response(writer, error_response)
                        continue
                    except ValueError as e:
                         logger.error(f"Invalid request format: {e}")
                         error_response = {"jsonrpc": "2.0", "error": {"code": -32600, "message": f"Invalid Request: {e}"}, "id": None}
                         await self._write_response(writer, error_response)
                         continue

                    # Handle the request concurrently
                    asyncio.create_task(self._process_and_respond(writer, request_data))

                except asyncio.IncompleteReadError:
                     logger.info("Stdin stream ended unexpectedly.")
                     break
                except ConnectionResetError:
                     logger.info("Stdin connection reset.")
                     break
                except Exception as e:
                     logger.exception(f"Error reading from stdin: {e}")
                     await asyncio.sleep(0.1) # Avoid tight loop on persistent read errors

        except asyncio.CancelledError:
            logger.info("Stdio server loop cancelled.")
        finally:
            logger.info("Stdio server loop finished.")
            if stdin_transport and not stdin_transport.is_closing():
                 stdin_transport.close()
            if writer_transport and not writer_transport.is_closing():
                 writer_transport.close()


    async def _process_and_respond(self, writer: asyncio.StreamWriter, request_data: Dict):
         """
         Helper coroutine to process a single request and send the response.

         Launched as a separate task to avoid blocking the main reader loop.

         Args:
             writer: The asyncio StreamWriter for writing the response to stdout.
             request_data: The raw request dictionary parsed from JSON.
         """
         # Import json here if not imported globally
         import json
         response_data = await self.handle_request(request_data)
         await self._write_response(writer, response_data)


    async def _write_response(self, writer: asyncio.StreamWriter, response_data: Dict):
         """
         Serialize and write a JSON response dictionary to the output stream.

         Ensures 'jsonrpc' and 'id' fields are present, masks sensitive data in the
         logged response string, and appends a newline character.

         Args:
             writer: The asyncio StreamWriter for writing to stdout.
             response_data: The response dictionary to send.
         """
         # Import json locally if needed, or ensure it's imported at module level
         # import json
         try:
              # Ensure response always has jsonrpc and id
              response_data["jsonrpc"] = response_data.get("jsonrpc", "2.0")
              # Use original request ID if available in response_data, otherwise None
              response_data["id"] = response_data.get("id", None)

              response_str = json.dumps(response_data)
              # Mask sensitive data in the response string before logging
              masked_response_str = mask_sensitive_data(response_str)
              logger.debug(f"Sending response: {masked_response_str}")

              writer.write(response_str.encode('utf-8') + b'\n')
              await writer.drain()
         except ConnectionResetError:
              logger.warning("Stdout connection reset while writing response.")
         except Exception as e:
              logger.exception(f"Error writing response to stdout: {e}")


    async def _run_sse_server(self):
        """
        Run the main server loop for Server-Sent Events (SSE) communication. (Placeholder)

        Requires integration with an async web framework like aiohttp or FastAPI
        to handle HTTP requests and SSE streams.
        """
        logger.warning("SSE server mode is not yet implemented.") # Requires a web framework like aiohttp/FastAPI
        # TODO: Implement SSE endpoint using a web framework (e.g., aiohttp, FastAPI)
        while self._running:
            await asyncio.sleep(1) # Placeholder loop

    async def handle_request(self, request_data: Dict) -> Dict:
        """
        Process a single incoming request dictionary.

        This method orchestrates the request lifecycle:
        1. Input Validation (using Pydantic if available)
        2. Rate Limiting
        3. Session Validation
        4. Dispatching the call to the appropriate Odoo handler (XMLRPC/JSONRPC) via the pool.
        5. Formatting the response (success or error) according to JSON-RPC 2.0.

        Args:
            request_data: The raw request dictionary parsed from JSON.

        Returns:
            A dictionary representing the JSON-RPC response.
        """
        # Mask raw request data before logging it fully
        masked_request_log = mask_sensitive_data(str(request_data)) # Mask string representation
        logger.debug(f"Handling raw request: {masked_request_log}")
        request_id = request_data.get("id") # Get ID early for error responses

        # 1. Input Validation
        validated_request = None
        try:
            validated_request = validate_request_data(request_data)
            # Now use validated_request.method, validated_request.params etc.
            # Note: validated_request.params might be a Pydantic model or a dict
            method_name = validated_request.method
            params = validated_request.params # This could be EchoParams, CallOdooParams, or dict
            session_id = params.session_id if hasattr(params, 'session_id') else None # Get session_id from validated params model if possible

        except ValidationError as e:
            logger.warning(f"Request validation failed: {e}")
            # Use the format_validation_error helper if needed, or just str(e)
            error_msg = f"Invalid params: {e}"
            return {"jsonrpc": "2.0", "error": {"code": -32602, "message": error_msg}, "id": request_id}
        except Exception as e: # Catch potential TypeError if Pydantic unavailable or other validation errors
             logger.error(f"Error during request validation phase: {e}", exc_info=True)
             return {"jsonrpc": "2.0", "error": {"code": -32600, "message": f"Invalid Request: {e}"}, "id": request_id}


        # 2. Rate Limiting
        if await self.rate_limiter.acquire():
             logger.debug(f"Rate limit check passed for method '{method_name}'.")
        else:
             # Rate limiter disabled or failed after wait
             if not self.rate_limiter.enabled:
                  logger.debug("Rate limiting disabled, proceeding.")
             else:
                  logger.error(f"Failed to acquire rate limit token for method '{method_name}' after waiting.")
                  return {"jsonrpc": "2.0", "error": {"code": -32000, "message": "Rate limit exceeded"}, "id": request_id}


        # 3. Authentication / Session Check (using session_id from validated params)
        session = None
        if session_id:
            session = self.session_manager.get_session(session_id) # get_session handles expiry check
            if not session:
                 logger.warning(f"Invalid or expired session ID provided: {session_id}")
                 return {"jsonrpc": "2.0", "error": {"code": -32001, "message": "Invalid or expired session"}, "id": request_id}
            logger.debug(f"Request validated for active session {session_id} (User ID: {session.user_id})")
        else:
            # No session ID provided in the request params
            # Decide policy: Allow only specific public methods or require session?
            # For now, log and proceed, but flag that stricter checks might be needed.
            logger.debug(f"Request for method '{method_name}' received without session ID.")
            # Example: Check if method is publicly allowed without session
            # PUBLIC_METHODS = {'echo', 'create_session'} # Example
            # if method_name not in PUBLIC_METHODS:
            #     return {"jsonrpc": "2.0", "error": {"code": -32001, "message": "Session ID required for this method"}, "id": request_id}


        # 4. Dispatch to appropriate handler/method (using validated data)
        response: Dict = {"jsonrpc": "2.0", "id": request_id}
        try:
            # Use validated method_name and params (which might be a Pydantic model)
            logger.info(f"Dispatching method: {method_name}")

            if method_name == "echo":
                 # Params should be EchoParams instance if validation worked
                 message_to_echo = params.message if isinstance(params, EchoParams) else "Default echo (validation fallback)"
                 response["result"] = message_to_echo

            elif method_name == "call_odoo":
                 # Params should be CallOdooParams instance if validation worked
                 if not isinstance(params, CallOdooParams):
                      # This case should ideally be caught by validation, but as a safeguard
                      raise ProtocolError("Internal error: Invalid params type for call_odoo after validation.")

                 model = params.model
                 odoo_method = params.odoo_method # Already aliased from 'method' by Pydantic
                 args = params.args
                 kwargs = params.kwargs
                 service = params.service # Optional service name for JSONRPC

                 # Use connection pool to execute
                 async with self.connection_pool.get_connection() as wrapper:
                      # Determine credentials to use
                      # Option 1: Use global credentials from config for all calls
                      current_uid = None # Not easily available unless fetched and stored
                      current_password = self.api_key # Use the global API key from config

                      # Option 2: Use session-specific credentials (more complex)
                      # if session:
                      #     current_uid = session.user_id
                      #     # Need a way to get password/api_key for this user_id!
                      #     # This might require storing it (insecurely) or other mechanism.
                      #     current_password = self.session_manager.get_password_for_session(session.session_id) # Fictional method
                      # else:
                      #     # Fallback to global or raise error if auth required
                      #     current_password = self.api_key

                      # For now, using global credentials (Option 1 simplified)
                      # XMLRPCHandler.execute_kw will fetch global UID if needed.

                      if isinstance(wrapper.connection, XMLRPCHandler):
                           # Pass None for uid/password to let execute_kw use its global/config fallback
                           result = wrapper.connection.execute_kw(model, odoo_method, args, kwargs, uid=None, password=None)
                           response["result"] = result
                      elif isinstance(wrapper.connection, JSONRPCHandler):
                           # TODO: JSONRPC authentication needs clarification.
                           # Does it use session cookies managed by requests.Session?
                           # Or does it need uid/password/token in args?
                           # Assuming session handles it for now.
                           # JSONRPC might need service name too
                           service = params.get("service", "object")
                           result = await wrapper.connection.call(service, odoo_method, args) # Assuming async call
                           response["result"] = result
                      else:
                           raise OdooMCPError("Unsupported connection handler type in pool.")

            else:
                raise OdooMCPError(f"Method not found: {method_name}")

        except OdooMCPError as e:
             logger.error(f"Error handling request: {e}", exc_info=True)
             # Map specific errors to JSON-RPC error codes if desired
             error_code = -32000 # Server error
             if isinstance(e, AuthError): error_code = -32001 # Custom Auth Error Code
             if isinstance(e, ProtocolError): error_code = -32602 # Invalid params / protocol issue
             if isinstance(e, NetworkError): error_code = -32002 # Custom Network Error Code

             response["error"] = {"code": error_code, "message": str(e)}
        except Exception as e:
             logger.exception(f"Unexpected error handling request: {e}")
             response["error"] = {"code": -32000, "message": f"Internal server error: {e}"}


        logger.debug(f"Sending response: {response}") # Consider masking sensitive data here too
        return response


# --- Main Execution Block ---

async def main(config_path: str = "odoo_mcp/config/config.dev.yaml"):
     """
     Asynchronous main entry point for the Odoo MCP Server.

     Loads configuration, sets up logging, creates the server instance,
     starts the server, and handles graceful shutdown on KeyboardInterrupt
     or other exceptions.

     Args:
         config_path: Path to the YAML configuration file.
     """
     # Load configuration
     try:
          import yaml # Requires PyYAML
          with open(config_path, 'r', encoding='utf-8') as f:
               config = yaml.safe_load(f)
          if not config:
               raise ConfigurationError(f"Configuration file '{config_path}' is empty or invalid.")
          logger.info(f"Configuration loaded successfully from {config_path}")
     except FileNotFoundError:
          logger.critical(f"Configuration file not found at {config_path}. Cannot start server.")
          return
     except yaml.YAMLError as e:
          logger.critical(f"Error parsing configuration file {config_path}: {e}")
          return
     except Exception as e:
          logger.critical(f"Failed to load configuration from {config_path}: {e}", exc_info=True)
          return

     # Setup Logging using the loaded config
     try:
          from odoo_mcp.core.logging_config import setup_logging
          setup_logging(config) # Pass the loaded config dict
     except Exception as e:
          # Log critical error if logging setup fails, using basic config
          logging.basicConfig(level=logging.ERROR)
          logging.critical(f"Failed to setup logging: {e}", exc_info=True)
          # Continue without advanced logging? Or exit? Let's exit.
          return

     # Create and run the server
     server = None
     try:
          server = MCPServer(config)
          await server.start()
          # Keep server running (indefinitely or until stopped)
          # This part depends on how start() is implemented (e.g., if it blocks)
          # If start() returns immediately, we need to keep the main task alive.
          if server._running: # Check if server started successfully
               logger.info("Server running. Press Ctrl+C to stop.")
               # Keep alive loop
               while server._running:
                    await asyncio.sleep(1)
          else:
               logger.error("Server failed to start properly.")

     except ConfigurationError as e:
          logger.critical(f"Server configuration error during initialization: {e}")
     except OdooMCPError as e:
          logger.critical(f"MCP Server error during startup: {e}", exc_info=True)
     except KeyboardInterrupt:
          logger.info("Shutdown signal (KeyboardInterrupt) received.")
     except Exception as e:
          logger.critical(f"An unexpected error occurred in the main loop: {e}", exc_info=True)
     finally:
          if server and server._running:
               logger.info("Initiating server shutdown...")
               await server.stop()
          else:
               logger.info("Server was not running or failed to start, no shutdown needed.")


if __name__ == "__main__":
     # Basic logging setup in case config loading fails before setup_logging is called
     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

     # TODO: Add argument parsing (e.g., using argparse) to specify config file path
     config_file = "odoo_mcp/config/config.dev.yaml" # Default path

     try:
          asyncio.run(main(config_file))
     except Exception as e:
          # Catch any unexpected errors during asyncio.run itself
          logger.critical(f"Critical error running the async main function: {e}", exc_info=True)

     # --- Old Conceptual Example ---
     # config = {
     #     'odoo_url': 'http://localhost:8069', # Replace
     #     'database': 'your_db',           # Replace
     #     'username': 'your_user',         # Replace
     #     'api_key': 'your_api_key',       # Replace
     #     'pool_size': 5,
     #     'timeout': 15,
     #     'protocol': 'xmlrpc', # or 'jsonrpc'
     #     'connection_type': 'stdio', # or 'sse'
     #     'requests_per_minute': 120,
     #     # Add other relevant config keys...
     # }
     # server = MCPServer(config)
     # try:
     #      await server.start()
     #      # Keep server running (e.g., wait for a shutdown signal)
     #      # For stdio, the loop might be inside start/run_stdio_server
     #      # For SSE, it might run indefinitely until stopped.
     #      # Example: Keep alive until Ctrl+C
     #      while True: await asyncio.sleep(3600)
     # except ConfigurationError as e:
     #      logger.critical(f"Server configuration error: {e}")
     # except KeyboardInterrupt:
     #      logger.info("Shutdown signal received.")
     # finally:
     #      await server.stop()

# if __name__ == "__main__":
#      logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
#      # asyncio.run(run_server()) # Uncomment to run
#      pass
