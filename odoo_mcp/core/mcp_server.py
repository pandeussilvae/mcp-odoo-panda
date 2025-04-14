import asyncio
import sys
import json
import logging
import signal
from typing import Dict, Any, Optional, Type, Union, List
import yaml
from datetime import datetime
import argparse # Import argparse here
import contextlib # Add contextlib import

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
# Import Pydantic validation components (Keep for potential internal use or future needs)
# from odoo_mcp.core.request_models import validate_request_params # No longer used in main dispatch
from pydantic import ValidationError # Keep for general validation errors if needed elsewhere
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

# --- Authentication Helper ---
async def _get_odoo_auth(
    session_manager: SessionManager,
    config: Dict[str, Any],
    params: Dict[str, Any] # Changed from tool_args to be more generic
) -> Dict[str, Union[int, str]]:
    """
    Determines Odoo authentication credentials (uid, password) based on
    session_id or direct uid/password provided in the input parameters.

    Returns:
        A dictionary containing 'uid' and 'password' for the Odoo call.
    Raises:
        AuthError: If authentication details are missing or invalid.
        ProtocolError: If parameter types are invalid.
        ConfigurationError: If session auth is used but global key/pwd is missing.
    """
    session_id = params.get("session_id")
    uid = params.get("uid")
    password = params.get("password")

    auth_uid: Optional[int] = None
    auth_pwd: Optional[str] = None

    if session_id:
        if not isinstance(session_id, str):
            raise ProtocolError("Invalid 'session_id' argument type", code=-32602)
        session = session_manager.get_session(session_id)
        if not session:
            raise AuthError(f"Invalid or expired session ID: {session_id}")
        auth_uid = session.user_id
        # Fallback to global password/key when using session ID, as execute_kw often needs it.
        auth_pwd = config.get('api_key') or config.get('password')
        if not auth_pwd:
            logger.error("CRITICAL: Using session auth but NO global api_key/password found in config.")
            raise ConfigurationError("Global api_key/password required in config when using session_id.")
        else:
            logger.warning("Using session ID for UID, falling back to global api_key/password from config.")
    elif uid is not None and password is not None:
        if not isinstance(uid, int):
            raise ProtocolError("Invalid 'uid' argument type", code=-32602)
        if not isinstance(password, str):
            raise ProtocolError("Invalid 'password' argument type", code=-32602)
        auth_uid = uid
        auth_pwd = password
    else:
        raise AuthError("Authentication required: provide either 'session_id' or both 'uid' and 'password'.")

    return {"uid": auth_uid, "password": auth_pwd}


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
            raw_params = request_data.get("params", {}) # Keep raw params for standard MCP methods

            # Define standard MCP methods that bypass Pydantic validation
            standard_mcp_methods = {
                "list_tools", "call_tool",
                "list_resource_templates", "read_resource"
                # "list_resources" # Not implemented yet
            }

            # 2. Rate Limiting
            # Acquire token, potentially waiting up to max_wait_seconds
            acquired = await self.rate_limiter.acquire()
            if not acquired:
                # If acquire returns False, it means it timed out waiting
                raise OdooMCPError("Rate limit exceeded and wait timed out. Please try again later.", code=-32000) # Custom error code

            # 3. Input Validation (Removed Pydantic validation for non-standard methods)
            #    Validation for standard MCP methods (list_tools, call_tool, etc.)
            #    is handled within their respective logic blocks.

            # 4. Method Dispatching
            logger.info(f"Received request for method: {method}")

            # --- Standard MCP Methods (using raw_params) ---
            if method == "list_tools":
                 response["result"] = {
                     "tools": [
                         # --- Basic Tools --- # (Keep existing tools)
                         {
                             "name": "echo",
                             "description": "Replies with the message provided.",
                             "inputSchema": { "type": "object", "properties": { "message": { "type": "string" } }, "required": ["message"] }
                         },
                         # --- Session Management Tools ---
                         {
                             "name": "create_session",
                             "description": "Creates an Odoo session using username/API key.",
                             "inputSchema": { "type": "object", "properties": { "username": { "type": "string" }, "api_key": { "type": "string" } }, "required": ["username", "api_key"] }
                         },
                         {
                             "name": "destroy_session",
                             "description": "Destroys an Odoo session.",
                             "inputSchema": { "type": "object", "properties": { "session_id": { "type": "string" } }, "required": ["session_id"] }
                         },
                         # --- Odoo Data Interaction Tools (CRUD + Search + Method Call) ---
                         {
                             "name": "odoo_search_read",
                             "description": "Searches Odoo records based on domain and returns specified fields.",
                             "inputSchema": {
                                 "type": "object",
                                 "properties": {
                                     "session_id": { "type": "string", "description": "Auth: Session ID." },
                                     "uid": { "type": "integer", "description": "Auth: User ID." },
                                     "password": { "type": "string", "description": "Auth: Password/API key." },
                                     "model": { "type": "string", "description": "Odoo model name (e.g., 'res.partner')." },
                                     "domain": { "type": "array", "description": "Odoo search domain (e.g., [['is_company', '=', True]]).", "default": [] },
                                     "fields": { "type": "array", "items": { "type": "string" }, "description": "List of fields to return (e.g., ['name', 'email']).", "default": [] },
                                     "limit": { "type": "integer", "description": "Maximum number of records.", "default": 80 }, # Odoo default limit
                                     "offset": { "type": "integer", "description": "Number of records to skip.", "default": 0 },
                                     "context": { "type": "object", "description": "Odoo context dictionary.", "default": {} }
                                 },
                                 "required": ["model"] # Auth handled separately
                             }
                         },
                         {
                             "name": "odoo_read",
                             "description": "Reads specific fields for given Odoo record IDs.",
                             "inputSchema": {
                                 "type": "object",
                                 "properties": {
                                     "session_id": { "type": "string", "description": "Auth: Session ID." },
                                     "uid": { "type": "integer", "description": "Auth: User ID." },
                                     "password": { "type": "string", "description": "Auth: Password/API key." },
                                     "model": { "type": "string", "description": "Odoo model name." },
                                     "ids": { "type": "array", "items": { "type": "integer" }, "description": "List of record IDs to read." },
                                     "fields": { "type": "array", "items": { "type": "string" }, "description": "List of fields to return.", "default": [] },
                                     "context": { "type": "object", "description": "Odoo context dictionary.", "default": {} }
                                 },
                                 "required": ["model", "ids"]
                             }
                         },
                         {
                             "name": "odoo_create",
                             "description": "Creates a new record in an Odoo model.",
                             "inputSchema": {
                                 "type": "object",
                                 "properties": {
                                     "session_id": { "type": "string", "description": "Auth: Session ID." },
                                     "uid": { "type": "integer", "description": "Auth: User ID." },
                                     "password": { "type": "string", "description": "Auth: Password/API key." },
                                     "model": { "type": "string", "description": "Odoo model name." },
                                     "values": { "type": "object", "description": "Dictionary of field values for the new record." },
                                     "context": { "type": "object", "description": "Odoo context dictionary.", "default": {} }
                                 },
                                 "required": ["model", "values"]
                             }
                         },
                         {
                             "name": "odoo_write",
                             "description": "Updates existing Odoo records.",
                             "inputSchema": {
                                 "type": "object",
                                 "properties": {
                                     "session_id": { "type": "string", "description": "Auth: Session ID." },
                                     "uid": { "type": "integer", "description": "Auth: User ID." },
                                     "password": { "type": "string", "description": "Auth: Password/API key." },
                                     "model": { "type": "string", "description": "Odoo model name." },
                                     "ids": { "type": "array", "items": { "type": "integer" }, "description": "List of record IDs to update." },
                                     "values": { "type": "object", "description": "Dictionary of field values to update." },
                                     "context": { "type": "object", "description": "Odoo context dictionary.", "default": {} }
                                 },
                                 "required": ["model", "ids", "values"]
                             }
                         },
                         {
                             "name": "odoo_unlink",
                             "description": "Deletes Odoo records.",
                             "inputSchema": {
                                 "type": "object",
                                 "properties": {
                                     "session_id": { "type": "string", "description": "Auth: Session ID." },
                                     "uid": { "type": "integer", "description": "Auth: User ID." },
                                     "password": { "type": "string", "description": "Auth: Password/API key." },
                                     "model": { "type": "string", "description": "Odoo model name." },
                                     "ids": { "type": "array", "items": { "type": "integer" }, "description": "List of record IDs to delete." },
                                     "context": { "type": "object", "description": "Odoo context dictionary.", "default": {} }
                                 },
                                 "required": ["model", "ids"]
                             }
                         },
                         {
                             "name": "odoo_call_method",
                             "description": "Calls a specific method on Odoo records.",
                             "inputSchema": {
                                 "type": "object",
                                 "properties": {
                                     "session_id": { "type": "string", "description": "Auth: Session ID." },
                                     "uid": { "type": "integer", "description": "Auth: User ID." },
                                     "password": { "type": "string", "description": "Auth: Password/API key." },
                                     "model": { "type": "string", "description": "Odoo model name." },
                                     "method": { "type": "string", "description": "Name of the method to call on the model/records." },
                                     "ids": { "type": "array", "items": { "type": "integer" }, "description": "List of record IDs to call the method on (can be empty for model methods)." },
                                     "args": { "type": "array", "description": "Positional arguments for the method.", "default": [] },
                                     "kwargs": { "type": "object", "description": "Keyword arguments for the method.", "default": {} },
                                     "context": { "type": "object", "description": "Odoo context dictionary.", "default": {} }
                                 },
                                 "required": ["model", "method", "ids"] # ids required even if empty list
                             }
                         }
                         # Potential future tools: get_report, etc.
                     ]
                 }
            elif method == "list_resource_templates":
                 response["result"] = {
                     "resourceTemplates": [
                         {
                             "uriTemplate": "odoo://{model}/{id}", # RFC 6570 template
                             "name": "Odoo Record",
                             "description": "Represents a single record in an Odoo model.",
                             "mimeType": "application/json",
                             # Define expected parameters for resolving the template in read_resource
                             "inputSchema": {
                                 "type": "object",
                                 "properties": {
                                     "uri": {"type": "string", "description": "The specific URI matching the template (e.g., 'odoo://res.partner/123')."},
                                     # Add auth params needed by our read_resource implementation
                                     "session_id": { "type": "string", "description": "Auth: Session ID." },
                                     "uid": { "type": "integer", "description": "Auth: User ID." },
                                     "password": { "type": "string", "description": "Auth: Password/API key." }
                                 },
                                 "required": ["uri"] # Auth handled by _get_odoo_auth logic
                             }
                         }
                     ]
                 }
            elif method == "read_resource":
                 uri = raw_params.get("uri")
                 if not uri or not isinstance(uri, str):
                     raise ProtocolError("Missing or invalid 'uri' parameter for read_resource", code=-32602)

                 # Parse URI: odoo://{model}/{id}
                 if not uri.startswith("odoo://"):
                     raise ProtocolError(f"Invalid URI scheme for read_resource: {uri}", code=-32602)
                 parts = uri[len("odoo://"):].split('/')
                 if len(parts) != 2:
                     raise ProtocolError(f"Invalid URI format for read_resource: {uri}. Expected odoo://model/id", code=-32602)
                 model_name, id_str = parts
                 try:
                     record_id = int(id_str)
                 except ValueError:
                     raise ProtocolError(f"Invalid record ID in URI for read_resource: {id_str}", code=-32602)

                 logger.info(f"Received read_resource request for URI: {uri} (Model: {model_name}, ID: {record_id})")

                 # Get Authentication Details (using raw_params which include uri, session_id, uid, password)
                 auth_details = await _get_odoo_auth(self.session_manager, self.config, raw_params)
                 auth_uid = auth_details["uid"]
                 auth_pwd = auth_details["password"]

                 # Fetch record data using 'read'
                 async with self.pool.get_connection() as wrapper:
                     handler_instance = wrapper.connection
                     # Fetch all readable fields by default. Consider adding optional 'fields' param?
                     record_data = handler_instance.execute_kw(
                         model_name, "read", [[record_id]], {}, # Read all fields for the given ID
                         uid=auth_uid, password=auth_pwd
                     )

                 if not record_data: # Odoo read returns empty list if ID not found or no access
                     # Use a specific MCP error code? RESOURCE_NOT_FOUND? Using generic for now.
                     raise OdooMCPError(f"Resource not found or access denied: {uri}", code=-32001) # Custom code

                 # Format response according to MCP ReadResource spec
                 response["result"] = {
                     "contents": [
                         {
                             "uri": uri,
                             "mimeType": "application/json",
                             # Odoo 'read' returns a list containing one dict
                             "text": json.dumps(record_data[0])
                         }
                     ]
                 }

            elif method == "call_tool":
                tool_name = raw_params.get("name")
                tool_args = raw_params.get("arguments", {}) # Arguments for the specific tool

                if not tool_name:
                    raise ProtocolError("Missing 'name' parameter for call_tool", code=-32602)
                if not isinstance(tool_args, dict):
                     raise ProtocolError("'arguments' parameter must be an object", code=-32602)

                logger.info(f"Received call_tool request for tool: {tool_name}")

                # --- Tool Dispatching ---
                odoo_result: Any = None # Variable to hold result from Odoo calls

                # Basic Tools
                if tool_name == "echo":
                    msg = tool_args.get("message")
                    if not isinstance(msg, str): raise ProtocolError("Invalid args for 'echo'", code=-32602)
                    odoo_result = msg # Simple echo
                # Session Management
                elif tool_name == "create_session":
                    username = tool_args.get("username")
                    api_key = tool_args.get("api_key")
                    if not (isinstance(username, str) and isinstance(api_key, str)):
                        raise ProtocolError("Invalid args for 'create_session'", code=-32602)
                    session = await self.session_manager.create_session(username=username, api_key=api_key)
                    odoo_result = {"session_id": session.session_id, "user_id": session.user_id}
                elif tool_name == "destroy_session":
                    session_id = tool_args.get("session_id")
                    if not isinstance(session_id, str): raise ProtocolError("Invalid args for 'destroy_session'", code=-32602)
                    self.session_manager.destroy_session(session_id)
                    odoo_result = True # Indicate success
                # Odoo Data Interaction
                elif tool_name in ["odoo_search_read", "odoo_read", "odoo_create", "odoo_write", "odoo_unlink", "odoo_call_method"]:
                    # Get Authentication Details using helper (passing tool_args)
                    auth_details = await _get_odoo_auth(self.session_manager, self.config, tool_args)
                    auth_uid = auth_details["uid"]
                    auth_pwd = auth_details["password"]

                    # Extract common parameters
                    model = tool_args.get("model")
                    context = tool_args.get("context", {})
                    if not isinstance(model, str): raise ProtocolError(f"Missing or invalid 'model' for {tool_name}", code=-32602)
                    if not isinstance(context, dict): raise ProtocolError(f"Invalid 'context' for {tool_name}", code=-32602)

                    # Get a connection and execute specific Odoo method
                    async with self.pool.get_connection() as wrapper:
                        handler_instance = wrapper.connection # This is XMLRPCHandler or JSONRPCHandler

                        if tool_name == "odoo_search_read":
                            domain = tool_args.get("domain", [])
                            fields = tool_args.get("fields", [])
                            limit = tool_args.get("limit", 80)
                            offset = tool_args.get("offset", 0)
                            if not isinstance(domain, list): raise ProtocolError("Invalid 'domain'", code=-32602)
                            if not isinstance(fields, list): raise ProtocolError("Invalid 'fields'", code=-32602)
                            if not isinstance(limit, int): raise ProtocolError("Invalid 'limit'", code=-32602)
                            if not isinstance(offset, int): raise ProtocolError("Invalid 'offset'", code=-32602)
                            odoo_result = handler_instance.execute_kw(
                                model, "search_read", [domain, fields], {"limit": limit, "offset": offset, "context": context},
                                uid=auth_uid, password=auth_pwd
                            )
                        elif tool_name == "odoo_read":
                            ids = tool_args.get("ids")
                            fields = tool_args.get("fields", [])
                            if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids): raise ProtocolError("Invalid 'ids'", code=-32602)
                            if not isinstance(fields, list): raise ProtocolError("Invalid 'fields'", code=-32602)
                            odoo_result = handler_instance.execute_kw(
                                model, "read", [ids, fields], {"context": context},
                                uid=auth_uid, password=auth_pwd
                            )
                        elif tool_name == "odoo_create":
                            values = tool_args.get("values")
                            if not isinstance(values, dict): raise ProtocolError("Invalid 'values'", code=-32602)
                            odoo_result = handler_instance.execute_kw(
                                model, "create", [values], {"context": context},
                                uid=auth_uid, password=auth_pwd
                            ) # Returns the ID of the created record
                        elif tool_name == "odoo_write":
                            ids = tool_args.get("ids")
                            values = tool_args.get("values")
                            if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids): raise ProtocolError("Invalid 'ids'", code=-32602)
                            if not isinstance(values, dict): raise ProtocolError("Invalid 'values'", code=-32602)
                            odoo_result = handler_instance.execute_kw(
                                model, "write", [ids, values], {"context": context},
                                uid=auth_uid, password=auth_pwd
                            ) # Returns True on success
                        elif tool_name == "odoo_unlink":
                            ids = tool_args.get("ids")
                            if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids): raise ProtocolError("Invalid 'ids'", code=-32602)
                            odoo_result = handler_instance.execute_kw(
                                model, "unlink", [ids], {"context": context},
                                uid=auth_uid, password=auth_pwd
                            ) # Returns True on success
                        elif tool_name == "odoo_call_method":
                            method_name = tool_args.get("method")
                            ids = tool_args.get("ids") # Can be empty list for model methods
                            args = tool_args.get("args", [])
                            kwargs = tool_args.get("kwargs", {})
                            if not isinstance(method_name, str): raise ProtocolError("Invalid 'method'", code=-32602)
                            if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids): raise ProtocolError("Invalid 'ids'", code=-32602)
                            if not isinstance(args, list): raise ProtocolError("Invalid 'args'", code=-32602)
                            if not isinstance(kwargs, dict): raise ProtocolError("Invalid 'kwargs'", code=-32602)
                            # Construct arguments for execute_kw: model, method, args_list, kwargs_dict
                            # For record methods, Odoo expects IDs as the first element in args_list
                            execute_args = [ids] + args if ids else args # Prepend non-empty IDs list
                            odoo_result = handler_instance.execute_kw(
                                model, method_name, execute_args, kwargs, # Pass context within kwargs? Odoo usually merges it. Let's add it explicitly.
                                uid=auth_uid, password=auth_pwd, context=context # Pass context here too
                            )

                else:
                    # Tool name not recognized
                    raise ProtocolError(f"Unknown tool name: {tool_name}", code=-32601) # Method not found equivalent

                # Format successful Odoo result according to MCP spec
                response["result"] = {"content": [{"type": "text", "text": json.dumps(odoo_result)}]}

            # --- No longer handling custom/original methods directly ---
            # elif method == "echo": ... (removed)
            # elif method == "create_session": ... (removed)
            # elif method == "destroy_session": ... (removed)
            # elif method == "call_odoo": ... (removed)

            else:
                 # If the method is not one of the standard MCP methods handled above
                 raise ProtocolError(f"Method not found: {method}", code=-32601)

        except (ProtocolError, AuthError, NetworkError, ConfigurationError, OdooMCPError) as e:
            # Log specific MCP/Odoo related errors with potentially less noise
            logger.warning(f"Error handling request: {e}", exc_info=isinstance(e, (NetworkError, OdooMCPError))) # Log trace for Network/OdooMCP errors
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
        # Use basic console logging if config load fails
        logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
        logger.critical(f"Configuration file not found: {config_path}")
        return
    except yaml.YAMLError as e:
        logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
        logger.critical(f"Error parsing configuration file {config_path}: {e}")
        return

    # Setup logging based on the loaded configuration
    # Redirect stdout to stderr during logging setup to avoid printing config messages to stdout
    with contextlib.redirect_stdout(sys.stderr):
        setup_logging(config)

    # Configure cache manager if cachetools is available
    if cache_manager and CACHE_TYPE == 'cachetools':
        try:
            cache_manager.configure(config)
        except Exception as e:
            logger.error(f"Failed to configure CacheManager: {e}", exc_info=True)
            # Decide if this is critical - maybe proceed without cache?
            # For now, log error and continue.

    # Run the server
    try:
        server = MCPServer(config)
        await server.run()
    except ConfigurationError as e:
        logger.critical(f"Server configuration error: {e}", exc_info=True)
    except Exception as e:
        logger.critical(f"Failed to start or run server: {e}", exc_info=True)

def main_cli():
    """Command Line Interface entry point."""
    # Example: Allow passing config path via command line argument
    # import argparse # Already imported at the top
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
        # Ensure logger is configured even if main() fails early
        if not logger.hasHandlers():
             logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        logger.info("Server stopped by user (KeyboardInterrupt).")
    finally:
         # Ensure logger is configured even if main() fails early
         if not logger.hasHandlers():
              logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
         logger.info("Exiting application.")

if __name__ == "__main__":
    main_cli() # Call the CLI entry point function
