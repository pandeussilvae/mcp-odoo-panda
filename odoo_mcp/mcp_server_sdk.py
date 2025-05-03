"""
Odoo MCP Server SDK implementation.
This module provides the main server implementation for Odoo MCP.
"""

import sys
import os
import json

# --- DEBUG STDIO PRECOCE: START ---
# Logga un marker su stderr per indicare che il debug precoce è attivo
try:
    sys.stderr.buffer.write(b"[DEBUG_START_STDIO]\n")
    sys.stderr.buffer.flush()

    # Sostituisce temporaneamente sys.stdout.buffer.write per loggare ogni scrittura
    original_stdout_buffer_write = sys.stdout.buffer.write
    def debug_early_stdout_write(data):
        try:
            # Logga su stderr i byte esatti che stanno per essere scritti su stdout
            sys.stderr.buffer.write(b"[DEBUG_EARLY_STDOUT] Writing bytes: ")
            sys.stderr.buffer.write(repr(data).encode('utf-8')) # Usa repr per mostrare \n, ecc.
            sys.stderr.buffer.write(b"\n")
            sys.stderr.buffer.flush()
        except Exception as e:
            # Se loggare su stderr fallisce, usa sys.__stderr__
            sys.__stderr__.write(f"[DEBUG_EARLY_STDOUT_ERROR] Failed to log early write: {e}\n".encode('utf-8'))
            sys.__stderr__.flush()

        # Scrivi i dati originali sul vero stdout
        return original_stdout_buffer_write(data)

    sys.stdout.buffer.write = debug_early_stdout_write

    sys.stderr.buffer.write(b"[DEBUG_START_STDIO] stdout buffer monkeypatched.\n")
    sys.stderr.buffer.flush()

except Exception as e:
    # Se il setup iniziale fallisce, stampa un errore critico usando il sys.stderr originale
    sys.__stderr__.write(f"[DEBUG_START_STDIO_CRITICAL_ERROR] Failed early debug setup: {e}\n".encode('utf-8'))
    sys.__stderr__.flush()
# --- DEBUG STDIO PRECOCE: END ---

import logging
import asyncio
from typing import Dict, Any, Optional, List, Union, Callable
from fastmcp import FastMCP, MCPRequest, MCPResponse
from fastmcp.decorators import mcp_handler, mcp_resource, mcp_tool
from aiohttp import web
import io
import contextlib

from odoo_mcp.core.protocol_handler import JsonRpcRequest, JsonRpcResponse
from odoo_mcp.core.connection_pool import ConnectionPool, initialize_connection_pool, get_connection_pool
from odoo_mcp.core.authenticator import Authenticator, initialize_authenticator, get_authenticator
from odoo_mcp.core.session_manager import SessionManager, initialize_session_manager, get_session_manager
from odoo_mcp.core.rate_limiter import RateLimiter, initialize_rate_limiter, get_rate_limiter
from odoo_mcp.performance.caching import CacheManager, initialize_cache_manager, get_cache_manager
from odoo_mcp.prompts.prompt_manager import PromptManager, initialize_prompt_manager, get_prompt_manager
from odoo_mcp.resources.resource_manager import ResourceManager, initialize_resource_manager, get_resource_manager
from odoo_mcp.tools.tool_manager import ToolManager, initialize_tool_manager, get_tool_manager
from odoo_mcp.core.capabilities_manager import CapabilitiesManager, ResourceTemplate, Tool, Prompt
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler
from odoo_mcp.core.jsonrpc_handler import JSONRPCHandler
from odoo_mcp.error_handling.exceptions import (
    OdooMCPError, AuthError, NetworkError, ProtocolError,
    ConfigurationError, ConnectionError, SessionError,
    OdooValidationError, OdooRecordNotFoundError, PoolTimeoutError,
    RateLimitError, ResourceError, ToolError, PromptError,
    CacheError, BusError
)
from odoo_mcp.core.logging_config import setup_logging

# Constants
SERVER_NAME = "odoo-mcp-server"
SERVER_VERSION = "2024.2.5"  # Using CalVer: YYYY.MM.DD
PROTOCOL_VERSION = "2024-11-05"  # MCP protocol version

logger = logging.getLogger(__name__)

class StdoutMonitor:
    """Monitor and control stdout output."""
    
    def __init__(self):
        self.original_stdout = sys.stdout
        self.original_stdout_write = sys.stdout.write
        self.buffer = io.StringIO()
        self.is_jsonrpc_response = False
        self.response_count = 0
        self.blocked_count = 0
        self.debug_mode = True  # Enable detailed debugging
        self.enabled = True  # Enable/disable the monitor
    
    def write(self, data: str) -> None:
        """Write data to stdout, monitoring for non-JSON-RPC output."""
        if not self.enabled:
            # If monitor is disabled, write directly to original stdout
            self.original_stdout_write(data)
            self.original_stdout.flush()
            return
        
        if self.debug_mode:
            # Log the exact bytes being written
            print(f"[DEBUG_STDOUT_WRITE] Attempting to write: {repr(data)}", file=sys.stderr, flush=True)
            print(f"[DEBUG_STDOUT_WRITE] Bytes: {[ord(c) for c in data]}", file=sys.stderr, flush=True)
        
        if not self.is_jsonrpc_response:
            self.blocked_count += 1
            if self.debug_mode:
                print(f"[DEBUG_STDOUT_WRITE] BLOCKED (not in JSON-RPC mode): {repr(data)}", file=sys.stderr, flush=True)
            return
        
        try:
            # Remove trailing newline for validation
            json_str = data.rstrip('\n')
            json_data = json.loads(json_str)
            
            # Validate required JSON-RPC 2.0 fields
            if not isinstance(json_data, dict):
                if self.debug_mode:
                    print(f"[DEBUG_STDOUT_WRITE] INVALID: Not a JSON object: {repr(data)}", file=sys.stderr, flush=True)
                return
            
            if 'jsonrpc' not in json_data or json_data['jsonrpc'] != '2.0':
                if self.debug_mode:
                    print(f"[DEBUG_STDOUT_WRITE] INVALID: Missing or invalid jsonrpc field: {repr(data)}", file=sys.stderr, flush=True)
                return
            
            if 'id' not in json_data:
                if self.debug_mode:
                    print(f"[DEBUG_STDOUT_WRITE] INVALID: Missing id field: {repr(data)}", file=sys.stderr, flush=True)
                return
            
            if 'result' not in json_data and 'error' not in json_data:
                if self.debug_mode:
                    print(f"[DEBUG_STDOUT_WRITE] INVALID: Missing result/error field: {repr(data)}", file=sys.stderr, flush=True)
                return
            
            # Validate newline termination
            if not data.endswith('\n'):
                if self.debug_mode:
                    print(f"[DEBUG_STDOUT_WRITE] INVALID: Missing newline termination: {repr(data)}", file=sys.stderr, flush=True)
                return
            
            # Check for multiple newlines
            if data.count('\n') > 1:
                if self.debug_mode:
                    print(f"[DEBUG_STDOUT_WRITE] INVALID: Multiple newlines: {repr(data)}", file=sys.stderr, flush=True)
                return
            
            # All validations passed, allow the write
            self.response_count += 1
            if self.debug_mode:
                print(f"[DEBUG_STDOUT_WRITE] ALLOWED write #{self.response_count}: {repr(data)}", file=sys.stderr, flush=True)
                print(f"[DEBUG_STDOUT_WRITE] Writing bytes: {[ord(c) for c in data]}", file=sys.stderr, flush=True)
            
            # Write the data directly to the original stdout
            self.original_stdout_write(data)
            self.original_stdout.flush()
            
        except json.JSONDecodeError:
            if self.debug_mode:
                print(f"[DEBUG_STDOUT_WRITE] INVALID: Not valid JSON: {repr(data)}", file=sys.stderr, flush=True)
            return
        except Exception as e:
            if self.debug_mode:
                print(f"[DEBUG_STDOUT_WRITE] ERROR validating response: {str(e)}", file=sys.stderr, flush=True)
            return
    
    def flush(self) -> None:
        """Flush stdout."""
        self.original_stdout.flush()
    
    def start_jsonrpc_response(self) -> None:
        """Mark the start of a JSON-RPC response."""
        self.is_jsonrpc_response = True
        if self.debug_mode:
            print(f"[DEBUG_STDOUT_WRITE] Starting JSON-RPC response #{self.response_count + 1}", file=sys.stderr, flush=True)
    
    def end_jsonrpc_response(self) -> None:
        """Mark the end of a JSON-RPC response."""
        self.is_jsonrpc_response = False
        if self.debug_mode:
            print(f"[DEBUG_STDOUT_WRITE] Ended JSON-RPC response #{self.response_count}", file=sys.stderr, flush=True)
    
    def disable(self) -> None:
        """Disable the stdout monitor."""
        self.enabled = False
        if self.debug_mode:
            print("[DEBUG_STDOUT_WRITE] Monitor disabled", file=sys.stderr, flush=True)
    
    def enable(self) -> None:
        """Enable the stdout monitor."""
        self.enabled = True
        if self.debug_mode:
            print("[DEBUG_STDOUT_WRITE] Monitor enabled", file=sys.stderr, flush=True)

class OdooMCPServer:
    """Main Odoo MCP Server implementation."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the Odoo MCP Server.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        
        # Get Odoo protocol (xmlrpc/jsonrpc)
        self.odoo_protocol = config.get('protocol', 'xmlrpc').lower()
        if self.odoo_protocol not in ['xmlrpc', 'jsonrpc']:
            raise ConfigurationError(f"Unsupported Odoo protocol: {self.odoo_protocol}")
        
        # Get MCP protocol (stdio/streamable_http)
        self.mcp_protocol = config.get('connection_type', 'stdio').lower()
        if self.mcp_protocol not in ['stdio', 'streamable_http']:
            raise ConfigurationError(f"Unsupported MCP protocol: {self.mcp_protocol}")
        
        # Initialize stdout monitor for stdio protocol
        if self.mcp_protocol == 'stdio':
            self.stdout_monitor = StdoutMonitor()
            sys.stdout = self.stdout_monitor
        
        # Initialize FastMCP
        self.app = FastMCP()
        
        # Configure MCP protocol
        if self.mcp_protocol == 'streamable_http':
            self.config['http'] = self.config.get('http', {})
            self.config['http']['streamable'] = True
            # Initialize aiohttp app for HTTP server
            self.web_app = web.Application()
            # Add routes for both root and /streamable paths
            self.web_app.router.add_post('/', self._handle_http_request)
            self.web_app.router.add_post('/streamable', self._handle_http_request)
        
        # Select handler class based on Odoo protocol
        handler_class = XMLRPCHandler if self.odoo_protocol == 'xmlrpc' else JSONRPCHandler
        
        # Initialize components
        try:
            initialize_connection_pool(config, handler_class)
            initialize_authenticator(config)
            initialize_session_manager(config)
            initialize_rate_limiter(config)
            initialize_cache_manager(config)
            initialize_prompt_manager(config)
            initialize_resource_manager(config)
            initialize_tool_manager(config)
        except ConfigurationError as e:
            logger.error(f"Failed to initialize components: {str(e)}")
            raise
        
        # Get manager instances
        try:
            self.connection_pool = get_connection_pool()
            self.authenticator = get_authenticator()
            self.session_manager = get_session_manager()
            self.rate_limiter = get_rate_limiter()
            self.cache_manager = get_cache_manager()
            self.prompt_manager = get_prompt_manager()
            self.resource_manager = get_resource_manager()
            self.tool_manager = get_tool_manager()
            
            # Initialize capabilities manager
            self.capabilities_manager = CapabilitiesManager(config)
            logger.info(f"CapabilitiesManager initialized: {self.capabilities_manager is not None}")
            
        except ConfigurationError as e:
            logger.error(f"Failed to get manager instances: {str(e)}")
            raise
        
        # Register handlers
        self._register_handlers()
        
        logger.info(f"Odoo MCP Server initialized with Odoo protocol: {self.odoo_protocol}, MCP protocol: {self.mcp_protocol}")

    def _register_handlers(self) -> None:
        """Register all MCP handlers."""
        # Register resource handlers
        self.app.register_resource_handler(self.handle_resource)
        
        # Register tool handlers
        self.app.register_tool_handler(self.handle_tool)
        
        # Register default handlers
        self.app.register_default_handler(self.handle_default)

    @mcp_handler
    async def handle_resource(self, request: MCPRequest) -> MCPResponse:
        """
        Handle resource requests.

        Args:
            request: MCP request object

        Returns:
            MCPResponse: Response object
        """
        try:
            # Validate session
            session = await self._validate_session(request)
            if not session:
                return MCPResponse.error("Invalid session")
            
            # Check rate limit
            if not self._check_rate_limit(request):
                return MCPResponse.error("Rate limit exceeded")
            
            # Execute resource operation
            result = await self._execute_resource_operation(request, session)
            return MCPResponse.success(result)
            
        except Exception as e:
            logger.error(f"Error handling resource request: {str(e)}")
            return MCPResponse.error(str(e))

    @mcp_handler
    async def handle_tool(self, request: MCPRequest) -> MCPResponse:
        """
        Handle tool requests.

        Args:
            request: MCP request object

        Returns:
            MCPResponse: Response object
        """
        try:
            # Validate session
            session = await self._validate_session(request)
            if not session:
                return MCPResponse.error("Invalid session")
            
            # Check rate limit
            if not self._check_rate_limit(request):
                return MCPResponse.error("Rate limit exceeded")
            
            # Execute tool operation
            result = await self._execute_tool_operation(request, session)
            return MCPResponse.success(result)
            
        except Exception as e:
            logger.error(f"Error handling tool request: {str(e)}")
            return MCPResponse.error(str(e))

    @mcp_handler
    async def handle_default(self, request: MCPRequest) -> MCPResponse:
        """
        Handle default requests.

        Args:
            request: MCP request object

        Returns:
            MCPResponse: Response object
        """
        try:
            # Validate session
            session = await self._validate_session(request)
            if not session:
                return MCPResponse.error("Invalid session")
            
            # Check rate limit
            if not self._check_rate_limit(request):
                return MCPResponse.error("Rate limit exceeded")
            
            # Process request
            result = await self._process_request(request, session)
            return MCPResponse.success(result)

        except Exception as e:
            logger.error(f"Error handling default request: {str(e)}")
            return MCPResponse.error(str(e))

    async def _validate_session(self, request: MCPRequest) -> Optional[Dict[str, Any]]:
        """
        Validate the session from the request.

        Args:
            request: MCP request object

        Returns:
            Optional[Dict[str, Any]]: Session data if valid, None otherwise
        """
        session_id = request.headers.get('X-Session-ID')
        if not session_id:
            return None
        
        return await self.session_manager.validate_session(session_id)

    def _check_rate_limit(self, request: MCPRequest) -> bool:
        """
        Check if the request is within rate limits.

        Args:
            request: MCP request object

        Returns:
            bool: True if within limits, False otherwise
        """
        client_id = request.headers.get('X-Client-ID', 'default')
        return self.rate_limiter.check_rate_limit(client_id)

    async def _execute_resource_operation(self, request: MCPRequest, session: Dict[str, Any]) -> Any:
        """
        Execute a resource operation.

        Args:
            request: MCP request object
            session: Session data

        Returns:
            Any: Operation result
        """
        resource_name = request.resource
        operation_name = request.operation
        
        # Get resource operation
        operation = self.resource_manager.get_operation(resource_name, operation_name)
        if not operation:
            raise ValueError(f"Operation not found: {resource_name}.{operation_name}")
        
        # Execute operation
        return await operation['handler'](session=session, **request.parameters)

    async def _execute_tool_operation(self, request: MCPRequest, session: Dict[str, Any]) -> Any:
        """
        Execute a tool operation.

        Args:
            request: MCP request object
            session: Session data

        Returns:
            Any: Operation result
        """
        tool_name = request.tool
        operation_name = request.operation
        
        # Get tool operation
        operation = self.tool_manager.get_operation(tool_name, operation_name)
        if not operation:
            raise ValueError(f"Operation not found: {tool_name}.{operation_name}")
        
        # Execute operation
        return await operation['handler'](session=session, **request.parameters)

    async def _process_request(self, request: MCPRequest, session: Dict[str, Any]) -> Any:
        """
        Process a default request.

        Args:
            request: MCP request object
            session: Session data

        Returns:
            Any: Request result
        """
        # Convert to JSON-RPC request
        jsonrpc_request = JsonRpcRequest(
            jsonrpc="2.0",
            method=request.method,
            params=request.parameters,
            id=request.id
        )
        
        # Process request
        jsonrpc_response = await self._process_jsonrpc_request(jsonrpc_request, session)
        
        # Convert to MCP response
        return jsonrpc_response.result

    async def _process_jsonrpc_request(self, request: JsonRpcRequest, session: Dict[str, Any]) -> JsonRpcResponse:
        """
        Process a JSON-RPC request.

        Args:
            request: JSON-RPC request object
            session: Session data

        Returns:
            JsonRpcResponse: JSON-RPC response object
        """
        try:
            # Get connection from pool
            connection = await self.connection_pool.get_connection()
            
            try:
                # Execute request
                result = await connection.execute(
                    method=request.method,
                    params=request.params,
                    uid=session['uid'],
                    password=session['password']
                )
                
                return JsonRpcResponse(
                    jsonrpc="2.0",
                    result=result,
                    id=request.id
                )
                
            finally:
                # Release connection
                await self.connection_pool.release_connection(connection)

        except Exception as e:
            logger.error(f"Error processing JSON-RPC request: {str(e)}")
            return JsonRpcResponse(
                jsonrpc="2.0",
                error={
                    'code': -32000,
                    'message': str(e)
                },
                id=request.id
            )

    async def _handle_http_request(self, request: web.Request) -> web.Response:
        """Handle HTTP requests."""
        logger.debug(f"_handle_http_request called. Self: {self}, Type: {type(self)}, CapabilitiesManager: {getattr(self, 'capabilities_manager', None)}")
        try:
            # Parse request body as JSON
            data = await request.json()
            logger.debug(f"Received request data: {json.dumps(data, indent=2)}")
            
            # Extract MCP request details
            method = data.get('method')
            request_id = data.get('id')
            params = data.get('params', {})  # Standard JSON-RPC uses 'params'
            
            if not method:
                logger.error("No method specified in request")
                return web.json_response({
                    'jsonrpc': '2.0',
                    'error': {
                        'code': -32600,
                        'message': 'Invalid request: method is required'
                    },
                    'id': request_id
                }, status=400)
            
            # List of methods that don't require authentication
            no_auth_methods = {
                'initialize',
                'list_resources',
                'list_tools',
                'list_prompts',
                'get_prompt',
                'create_session',  # Add session creation method
                'login'  # Add login method if needed
            }
            
            # Create MCP request object with all headers
            mcp_request = MCPRequest(
                method=method,
                parameters=params,
                id=request_id,
                headers=dict(request.headers)  # Pass all headers to MCPRequest
            )
            
            # Log all request headers for debugging
            logger.debug(f"Request headers: {dict(request.headers)}")
            
            # Route the request based on method type
            if method in no_auth_methods:
                logger.info(f"Handling public method: {method}")
                # Handle methods that don't require authentication
                if method == 'initialize':
                    if not hasattr(self, 'capabilities_manager'):
                        logger.error("CapabilitiesManager not initialized")
                        return web.json_response({
                            'jsonrpc': '2.0',
                            'error': {
                                'code': -32603,
                                'message': 'Server not properly initialized'
                            },
                            'id': request_id
                        }, status=500)
                    response = await self._handle_initialize(mcp_request)
                elif method == 'list_resources':
                    response = await self._handle_list_resources(mcp_request)
                elif method == 'list_tools':
                    response = await self._handle_list_tools(mcp_request)
                elif method == 'list_prompts':
                    response = await self._handle_list_prompts(mcp_request)
                elif method == 'get_prompt':
                    response = await self._handle_get_prompt(mcp_request)
                elif method == 'create_session':
                    response = await self._handle_create_session(mcp_request)
                elif method == 'login':
                    response = await self._handle_login(mcp_request)
            else:
                logger.info(f"Handling authenticated method: {method}")
                
                # Check for session ID header
                session_id = request.headers.get('X-Session-ID')
                logger.debug(f"Session ID from headers: {session_id}")
                
                if not session_id:
                    logger.warning(f"No session ID provided for authenticated method: {method}")
                    return web.json_response({
                        'jsonrpc': '2.0',
                        'error': {
                            'code': -32001,
                            'message': 'No session ID provided'
                        },
                        'id': request_id
                    }, status=401)
                
                try:
                    # Validate session using session manager
                    session = await self.session_manager.validate_session(session_id)
                    if not session:
                        logger.warning(f"Invalid session for method: {method}")
                        return web.json_response({
                            'jsonrpc': '2.0',
                            'error': {
                                'code': -32001,
                                'message': 'Invalid session'
                            },
                            'id': request_id
                        }, status=401)
                    
                    # Add session to request parameters
                    mcp_request.parameters['session'] = session
                    
                    # Route to appropriate handler based on request type
                    if hasattr(mcp_request, 'resource') and mcp_request.resource:
                        response = await self.handle_resource(mcp_request)
                    elif hasattr(mcp_request, 'tool') and mcp_request.tool:
                        response = await self.handle_tool(mcp_request)
                    else:
                        response = await self.handle_default(mcp_request)
                        
                except AuthError as e:
                    logger.error(f"Authentication error for method {method}: {str(e)}")
                    return web.json_response({
                        'jsonrpc': '2.0',
                        'error': {
                            'code': -32001,
                            'message': str(e)
                        },
                        'id': request_id
                    }, status=401)
                except Exception as e:
                    logger.error(f"Error handling authenticated request: {str(e)}")
                    return web.json_response({
                        'jsonrpc': '2.0',
                        'error': {
                            'code': -32603,
                            'message': str(e)
                        },
                        'id': request_id
                    }, status=500)
            
            # Convert MCPResponse to JSON-RPC response
            response_dict = {
                'jsonrpc': '2.0',
                'id': request_id
            }
            
            if response.success:
                response_dict['result'] = response.data
            else:
                response_dict['error'] = {
                    'code': -32000,
                    'message': response.error
                }
            
            logger.debug(f"Sending response: {json.dumps(response_dict, indent=2)}")
            return web.json_response(response_dict)
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in request body: {str(e)}")
            return web.json_response({
                'jsonrpc': '2.0',
                'error': {
                    'code': -32700,
                    'message': 'Parse error: Invalid JSON'
                },
                'id': None
            }, status=400)
        except Exception as e:
            logger.error(f"Error handling HTTP request: {str(e)}")
            return web.json_response({
                'jsonrpc': '2.0',
                'error': {
                    'code': -32603,
                    'message': str(e)
                },
                'id': None
            }, status=500)

    async def _handle_initialize(self, request: MCPRequest) -> MCPResponse:
        """Handle initialize request."""
        logger.debug(f"_handle_initialize called. Self: {self}, Type: {type(self)}, CapabilitiesManager: {getattr(self, 'capabilities_manager', None)}")
        try:
            if not hasattr(self, 'capabilities_manager'):
                logger.error("CapabilitiesManager not initialized in _handle_initialize")
                return MCPResponse.error("Server not properly initialized")
            
            # Get server capabilities following MCP 2025-03-26 specification
            capabilities = self.capabilities_manager.get_capabilities()
            
            # Create response with correct protocol version and server info
            # Following exact MCP 2025-03-26 specification structure
            response_data = {
                'protocolVersion': PROTOCOL_VERSION,
                'serverInfo': {
                    'name': SERVER_NAME,
                    'version': SERVER_VERSION
                },
                'capabilities': capabilities,
                'instructions': 'Optional instructions for the client'  # Optional field as per spec
            }
            
            # Log the complete response structure for debugging
            logger.info(f"Initialize response data structure: {json.dumps(response_data, indent=2)}")
            
            # Create MCPResponse with the data
            response = MCPResponse.success(response_data)
            
            # Log the complete JSON-RPC response that will be sent
            json_rpc_response = {
                'jsonrpc': '2.0',
                'id': request.id,
                'result': response_data
            }
            logger.info(f"Complete JSON-RPC initialize response: {json.dumps(json_rpc_response, indent=2)}")
            
            return response
            
        except Exception as e:
            logger.error(f"Error handling initialize request: {str(e)}")
            return MCPResponse.error(str(e))

    async def _handle_list_resources(self, request: MCPRequest) -> MCPResponse:
        """Handle list_resources request."""
        try:
            # Get list of resources from capabilities manager
            resources = self.capabilities_manager.list_resources()
            
            # Log the response for debugging
            logger.debug(f"List resources response: {json.dumps(resources, indent=2)}")
            
            return MCPResponse(
                success=True,
                data={"resources": resources}
            )
        except Exception as e:
            logger.error(f"Error listing resources: {str(e)}")
            return MCPResponse(
                success=False,
                error=f"Failed to list resources: {str(e)}"
            )

    async def _handle_list_tools(self, request: MCPRequest) -> MCPResponse:
        """Handle list_tools request."""
        try:
            tools = self.capabilities_manager.list_tools()
            return MCPResponse.success({'tools': tools})
        except Exception as e:
            logger.error(f"Error handling list_tools request: {str(e)}")
            return MCPResponse.error(str(e))

    async def _handle_list_prompts(self, request: MCPRequest) -> MCPResponse:
        """Handle list_prompts request."""
        try:
            prompts = self.capabilities_manager.list_prompts()
            return MCPResponse.success({'prompts': prompts})
        except Exception as e:
            logger.error(f"Error handling list_prompts request: {str(e)}")
            return MCPResponse.error(str(e))

    async def _handle_get_prompt(self, request: MCPRequest) -> MCPResponse:
        """Handle get_prompt request."""
        try:
            name = request.parameters.get('name')
            args = request.parameters.get('args', {})
            
            prompt = self.capabilities_manager.get_prompt(name)
            if not prompt:
                return MCPResponse.error(f"Prompt not found: {name}")
            
            return MCPResponse.success(prompt)
        except Exception as e:
            logger.error(f"Error handling get_prompt request: {str(e)}")
            return MCPResponse.error(str(e))

    async def _handle_create_session(self, request: MCPRequest) -> MCPResponse:
        """
        Handle create_session request.
        
        Expected request format:
        {
            "jsonrpc": "2.0",
            "method": "create_session",
            "params": {
                "credentials": {
                    "username": "user",
                    "password": "pass",
                    "database": "db"
                }
            },
            "id": 1
        }
        
        Successful response format:
        {
            "jsonrpc": "2.0",
            "result": {
                "session": {
                    "id": "session_id",
                    "expires_at": "timestamp"
                }
            },
            "id": 1
        }
        """
        try:
            logger.info("Handling create_session request")
            
            # Extract credentials from parameters
            credentials = request.parameters.get('credentials', {})
            if not credentials:
                logger.error("No credentials provided in create_session request")
                return MCPResponse.error("No credentials provided")
            
            # Validate required credential fields
            required_fields = ['username', 'password', 'database']
            missing_fields = [field for field in required_fields if field not in credentials]
            if missing_fields:
                logger.error(f"Missing required credential fields: {missing_fields}")
                return MCPResponse.error(f"Missing required credential fields: {', '.join(missing_fields)}")
            
            # Authenticate with Odoo
            try:
                auth_result = await self.authenticator.authenticate(credentials)
                if not auth_result:
                    logger.error("Authentication failed in create_session")
                    return MCPResponse.error("Authentication failed")
            except AuthError as e:
                logger.error(f"Authentication error in create_session: {str(e)}")
                return MCPResponse.error(str(e))
            
            # Create MCP session
            try:
                session = await self.session_manager.create_session(credentials)
                if not session:
                    logger.error("Failed to create session")
                    return MCPResponse.error("Failed to create session")
                
                logger.info(f"Session created successfully: {session['id']}")
                
                # Return session information
                return MCPResponse.success({
                    'session': {
                        'id': session['id'],
                        'expires_at': session['expires_at']
                    }
                })
            except Exception as e:
                logger.error(f"Error creating session: {str(e)}")
                return MCPResponse.error(f"Failed to create session: {str(e)}")
                
        except Exception as e:
            logger.error(f"Unexpected error in create_session: {str(e)}")
            return MCPResponse.error(f"Unexpected error: {str(e)}")

    async def _handle_login(self, request: MCPRequest) -> MCPResponse:
        """
        Handle login request.
        
        Expected request format:
        {
            "jsonrpc": "2.0",
            "method": "login",
            "params": {
                "credentials": {
                    "username": "user",
                    "password": "pass",
                    "database": "db"
                }
            },
            "id": 1
        }
        
        Successful response format:
        {
            "jsonrpc": "2.0",
            "result": {
                "session": {
                    "id": "session_id",
                    "expires_at": "timestamp"
                }
            },
            "id": 1
        }
        """
        try:
            logger.info("Handling login request")
            
            # Extract credentials from parameters
            credentials = request.parameters.get('credentials', {})
            if not credentials:
                logger.error("No credentials provided in login request")
                return MCPResponse.error("No credentials provided")
            
            # Validate required credential fields
            required_fields = ['username', 'password', 'database']
            missing_fields = [field for field in required_fields if field not in credentials]
            if missing_fields:
                logger.error(f"Missing required credential fields: {missing_fields}")
                return MCPResponse.error(f"Missing required credential fields: {', '.join(missing_fields)}")
            
            # Authenticate with Odoo
            try:
                auth_result = await self.authenticator.authenticate(credentials)
                if not auth_result:
                    logger.error("Authentication failed in login")
                    return MCPResponse.error("Authentication failed")
            except AuthError as e:
                logger.error(f"Authentication error in login: {str(e)}")
                return MCPResponse.error(str(e))
            
            # Create MCP session
            try:
                session = await self.session_manager.create_session(credentials)
                if not session:
                    logger.error("Failed to create session after login")
                    return MCPResponse.error("Failed to create session")
                
                logger.info(f"Login successful, session created: {session['id']}")
                
                # Return session information
                return MCPResponse.success({
                    'session': {
                        'id': session['id'],
                        'expires_at': session['expires_at']
                    }
                })
            except Exception as e:
                logger.error(f"Error creating session after login: {str(e)}")
                return MCPResponse.error(f"Failed to create session: {str(e)}")
                
        except Exception as e:
            logger.error(f"Unexpected error in login: {str(e)}")
            return MCPResponse.error(f"Unexpected error: {str(e)}")

    async def _handle_resource_read(self, request: MCPRequest) -> MCPResponse:
        """Handle resource read request.
        
        According to MCP 2025-03-26 specification, the response should have this structure:
        {
          "jsonrpc": "2.0",
          "result": {
            "contents": [
              {
                "uri": "string",
                "type": "string",
                "data": any
              }
            ]
          },
          "id": number
        }
        """
        try:
            # Extract URI from parameters
            uri = request.parameters.get('uri')
            if not uri:
                return MCPResponse.error("No URI provided")
            
            # Extract resource name from URI (format: odoo://res.partner)
            if not uri.startswith('odoo://'):
                return MCPResponse.error("Invalid URI format")
            
            resource_name = uri[7:]  # Remove 'odoo://' prefix
            
            # Get resource from capabilities manager
            resource = self.capabilities_manager.get_resource(resource_name)
            if not resource:
                return MCPResponse.error(f"Resource not found: {resource_name}")
            
            # Convert resource to dictionary format
            resource_dict = {
                "name": resource.name,
                "type": resource.type.value,
                "description": resource.description,
                "operations": resource.operations,
                "parameters": resource.parameters or {},
                "uri": f"odoo://{resource.name}"
            }
            
            # Format response according to MCP 2025-03-26 specification
            response_data = {
                "contents": [
                    {
                        "uri": uri,
                        "type": resource.type.value,
                        "data": resource_dict
                    }
                ]
            }
            
            return MCPResponse.success(response_data)
            
        except Exception as e:
            logger.error(f"Error handling resource read request: {str(e)}")
            return MCPResponse.error(str(e))

    async def start(self) -> None:
        """Start the MCP server."""
        try:
            # Get host and port from http config if using streamable_http
            if self.mcp_protocol == 'streamable_http':
                http_config = self.config.get('http', {})
                host = http_config.get('host', '0.0.0.0')
                port = http_config.get('port', 8080)
            else:
                host = self.config.get('host', 'localhost')
                port = self.config.get('port', 8000)
            
            logger.info(f"Starting Odoo MCP Server on {host}:{port} with protocol {self.mcp_protocol}")
            
            # Start the server
            if self.mcp_protocol == 'streamable_http':
                # Start the HTTP server
                runner = web.AppRunner(self.web_app)
                await runner.setup()
                self._started_mcp_server_instance = web.TCPSite(runner, host, port)
                await self._started_mcp_server_instance.start()
                logger.info(f"Odoo MCP Server started successfully on {host}:{port}")
            else:
                # For stdio protocol, start reading from stdin
                logger.info("Starting stdio protocol handler")
                await self._start_stdio_handler()
                logger.info("Odoo MCP Server started successfully in stdio mode")
            
        except Exception as e:
            logger.error(f"Error starting server: {str(e)}")
            raise

    async def _start_stdio_handler(self) -> None:
        """Start the stdio protocol handler."""
        try:
            # Create a stream reader for stdin
            loop = asyncio.get_event_loop()
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await loop.connect_read_pipe(lambda: protocol, sys.stdin)
            
            print("[StdioHandler] Started reading from stdin", file=sys.stderr, flush=True)
            
            # Start the message processing loop
            while True:
                try:
                    # Read a line from stdin (messages are delimited by newlines)
                    data = await reader.readline()
                    if not data:
                        print("[StdioHandler] Received empty data from stdin", file=sys.stderr, flush=True)
                        continue
                    
                    # Decode the data
                    message = data.decode('utf-8').strip()
                    print(f"[StdioHandler] Received message: {repr(message)}", file=sys.stderr, flush=True)
                    
                    try:
                        # Parse the JSON-RPC message
                        request_data = json.loads(message)
                        print(f"[StdioHandler] Parsed JSON-RPC message: {json.dumps(request_data, indent=2)}", file=sys.stderr, flush=True)
                        
                        # Extract session ID from params for stdio protocol
                        params = request_data.get('params', {})
                        session_id = None
                        
                        # Try to get session ID from different possible locations in params
                        if isinstance(params, dict):
                            # Try direct session_id field
                            session_id = params.get('session_id')
                            # Try sessionId field
                            if not session_id:
                                session_id = params.get('sessionId')
                            # Try context.session_id
                            if not session_id and 'context' in params:
                                context = params.get('context', {})
                                session_id = context.get('session_id') or context.get('sessionId')
                        
                        print(f"[StdioHandler] Extracted session ID: {session_id}", file=sys.stderr, flush=True)
                        
                        # Create MCP request with session ID in headers for stdio protocol
                        mcp_request = MCPRequest(
                            method=request_data.get('method'),
                            parameters=params,
                            id=request_data.get('id', 0),  # Default to 0 if no id provided
                            headers={'X-Session-ID': session_id} if session_id else {}
                        )
                        
                        # Process the request
                        response = await self._process_mcp_request(mcp_request)
                        
                        # If response is None (e.g., for notifications), don't send a response
                        if response is None:
                            continue
                        
                        # Validate response structure
                        if not isinstance(response, dict):
                            print(f"[StdioHandler] Invalid response type: {type(response)}", file=sys.stderr, flush=True)
                            response = {
                                'jsonrpc': '2.0',
                                'error': {
                                    'code': -32603,
                                    'message': 'Internal error: Invalid response format'
                                },
                                'id': request_data.get('id', 0)
                            }
                        
                        # Ensure response has required JSON-RPC 2.0 fields
                        if 'jsonrpc' not in response or response['jsonrpc'] != '2.0':
                            print(f"[StdioHandler] Invalid response: missing or invalid jsonrpc field", file=sys.stderr, flush=True)
                            response = {
                                'jsonrpc': '2.0',
                                'error': {
                                    'code': -32603,
                                    'message': 'Internal error: Invalid response format'
                                },
                                'id': request_data.get('id', 0)
                            }
                        
                        if 'id' not in response:
                            print(f"[StdioHandler] Invalid response: missing id field", file=sys.stderr, flush=True)
                            response = {
                                'jsonrpc': '2.0',
                                'error': {
                                    'code': -32603,
                                    'message': 'Internal error: Missing response ID'
                                },
                                'id': 0
                            }
                        
                        if 'result' not in response and 'error' not in response:
                            print(f"[StdioHandler] Invalid response: missing result/error field", file=sys.stderr, flush=True)
                            response = {
                                'jsonrpc': '2.0',
                                'error': {
                                    'code': -32603,
                                    'message': 'Internal error: Missing result/error field'
                                },
                                'id': response.get('id', 0)
                            }
                        
                        # Prepare the response string with minimal separators and single newline
                        response_str = json.dumps(response, separators=(',', ':')) + '\n'
                        print(f"[StdioHandler] Prepared response: {repr(response_str)}", file=sys.stderr, flush=True)
                        print(f"[StdioHandler] Response bytes: {[ord(c) for c in response_str]}", file=sys.stderr, flush=True)
                        
                        # Mark start of JSON-RPC response
                        self.stdout_monitor.start_jsonrpc_response()
                        
                        # Write the response to stdout
                        sys.stdout.write(response_str)
                        sys.stdout.flush()
                        
                        # Mark end of JSON-RPC response
                        self.stdout_monitor.end_jsonrpc_response()
                        
                    except json.JSONDecodeError as e:
                        print(f"[StdioHandler] Failed to parse JSON message: {str(e)}", file=sys.stderr, flush=True)
                        error_response = {
                            'jsonrpc': '2.0',
                            'error': {
                                'code': -32700,
                                'message': 'Parse error: Invalid JSON'
                            },
                            'id': request_data.get('id', 0) if 'request_data' in locals() else 0
                        }
                        error_str = json.dumps(error_response, separators=(',', ':')) + '\n'
                        print(f"[StdioHandler] Prepared error response: {repr(error_str)}", file=sys.stderr, flush=True)
                        print(f"[StdioHandler] Error response bytes: {[ord(c) for c in error_str]}", file=sys.stderr, flush=True)
                        
                        # Mark start of JSON-RPC response
                        self.stdout_monitor.start_jsonrpc_response()
                        
                        # Write error response
                        sys.stdout.write(error_str)
                        sys.stdout.flush()
                        
                        # Mark end of JSON-RPC response
                        self.stdout_monitor.end_jsonrpc_response()
                        
                except Exception as e:
                    print(f"[StdioHandler] Error processing stdin message: {str(e)}", file=sys.stderr, flush=True)
                    error_response = {
                        'jsonrpc': '2.0',
                        'error': {
                            'code': -32603,
                            'message': str(e)
                        },
                        'id': request_data.get('id', 0) if 'request_data' in locals() else 0
                    }
                    error_str = json.dumps(error_response, separators=(',', ':')) + '\n'
                    print(f"[StdioHandler] Prepared error response: {repr(error_str)}", file=sys.stderr, flush=True)
                    print(f"[StdioHandler] Error response bytes: {[ord(c) for c in error_str]}", file=sys.stderr, flush=True)
                    
                    # Mark start of JSON-RPC response
                    self.stdout_monitor.start_jsonrpc_response()
                    
                    # Write error response
                    sys.stdout.write(error_str)
                    sys.stdout.flush()
                    
                    # Mark end of JSON-RPC response
                    self.stdout_monitor.end_jsonrpc_response()
                    
        except Exception as e:
            print(f"[StdioHandler] Error in stdio handler: {str(e)}", file=sys.stderr, flush=True)
            raise

    async def _process_mcp_request(self, request: MCPRequest) -> Dict[str, Any]:
        """Process an MCP request and return the response."""
        try:
            # List of methods that don't require authentication
            no_auth_methods = {
                'initialize',
                'list_resources',
                'resources/list',  # Add both formats
                'list_tools',
                'tools/list',      # Add both formats
                'list_prompts',
                'prompts/list',    # Add both formats
                'get_prompt',
                'create_session',
                'login',
                'resources/read',   # Add resources/read as public method
                'resources_read'    # Add alternative format
            }
            
            # Ensure request.id is never None
            request_id = request.id if request.id is not None else 0
            
            # Handle notifications (they don't require authentication and don't need a response)
            if request.method.startswith('notifications/'):
                logger.info(f"Handling notification: {request.method}")
                # For notifications, we don't need to send a response
                return None
            
            # Route the request based on method type
            if request.method in no_auth_methods:
                logger.info(f"Handling public method: {request.method}")
                # Handle methods that don't require authentication
                if request.method == 'initialize':
                    if not hasattr(self, 'capabilities_manager'):
                        logger.error("CapabilitiesManager not initialized")
                        return {
                            'jsonrpc': '2.0',
                            'error': {
                                'code': -32603,
                                'message': 'Server not properly initialized'
                            },
                            'id': request_id
                        }
                    response = await self._handle_initialize(request)
                elif request.method in ['list_resources', 'resources/list']:
                    response = await self._handle_list_resources(request)
                elif request.method in ['list_tools', 'tools/list']:
                    response = await self._handle_list_tools(request)
                elif request.method in ['list_prompts', 'prompts/list']:
                    response = await self._handle_list_prompts(request)
                elif request.method == 'get_prompt':
                    response = await self._handle_get_prompt(request)
                elif request.method == 'create_session':
                    response = await self._handle_create_session(request)
                elif request.method == 'login':
                    response = await self._handle_login(request)
                elif request.method in ['resources/read', 'resources_read']:
                    # Handle resources/read as a public method
                    response = await self._handle_resource_read(request)
            else:
                logger.info(f"Handling authenticated method: {request.method}")
                # For all other methods, validate session first
                session_id = request.headers.get('X-Session-ID')
                if not session_id:
                    logger.warning(f"No session ID provided for method: {request.method}")
                    return {
                        'jsonrpc': '2.0',
                        'error': {
                            'code': -32001,
                            'message': 'No session ID provided'
                        },
                        'id': request_id
                    }
                
                try:
                    # Validate session using session manager
                    session = await self.session_manager.validate_session(session_id)
                    if not session:
                        logger.warning(f"Invalid session for method: {request.method}")
                        return {
                            'jsonrpc': '2.0',
                            'error': {
                                'code': -32001,
                                'message': 'Invalid session'
                            },
                            'id': request_id
                        }
                    
                    # Add session to request parameters
                    request.parameters['session'] = session
                    
                    # Route to appropriate handler based on request type
                    if hasattr(request, 'resource') and request.resource:
                        response = await self.handle_resource(request)
                    elif hasattr(request, 'tool') and request.tool:
                        response = await self.handle_tool(request)
                    else:
                        response = await self.handle_default(request)
                        
                except AuthError as e:
                    logger.error(f"Authentication error for method {request.method}: {str(e)}")
                    return {
                        'jsonrpc': '2.0',
                        'error': {
                            'code': -32001,
                            'message': str(e)
                        },
                        'id': request_id
                    }
                except Exception as e:
                    logger.error(f"Error handling authenticated request: {str(e)}")
                    return {
                        'jsonrpc': '2.0',
                        'error': {
                            'code': -32603,
                            'message': str(e)
                        },
                        'id': request_id
                    }
            
            # If response is None (e.g., for notifications), don't send a response
            if response is None:
                return None
            
            # Convert MCPResponse to JSON-RPC response
            response_dict = {
                'jsonrpc': '2.0',
                'id': request_id
            }
            
            if response.success:
                response_dict['result'] = response.data
            else:
                response_dict['error'] = {
                    'code': -32000,
                    'message': response.error
                }
            
            logger.debug(f"Processed request successfully: {json.dumps(response_dict, indent=2)}")
            return response_dict
            
        except Exception as e:
            logger.error(f"Error processing MCP request: {str(e)}")
            return {
                'jsonrpc': '2.0',
                'error': {
                    'code': -32603,
                    'message': str(e)
                },
                'id': request.id if request.id is not None else 0
            }

    async def stop(self) -> None:
        """Stop the MCP server."""
        try:
            logger.info("Stopping Odoo MCP Server...")
            if hasattr(self, '_started_mcp_server_instance') and self._started_mcp_server_instance is not None:
                await self._started_mcp_server_instance.stop()
            
            # Restore original stdout if using stdio protocol
            if self.mcp_protocol == 'stdio' and hasattr(self, 'stdout_monitor'):
                sys.stdout = self.stdout_monitor.original_stdout
            
            logger.info("Odoo MCP Server stopped")
        except Exception as e:
            logger.error(f"Error stopping server: {str(e)}")
            raise

def create_server(config: Dict[str, Any]) -> OdooMCPServer:
    """
    Create a new Odoo MCP Server instance.

    Args:
        config: Configuration dictionary

    Returns:
        OdooMCPServer: Server instance
    """
    return OdooMCPServer(config)

async def run_server(config: Dict[str, Any]) -> None:
    """
    Run the Odoo MCP Server.

    Args:
        config: Configuration dictionary
    """
    server = None
    try:
        logger.info("Creating Odoo MCP Server instance...")
        server = create_server(config)
        
        logger.info("Starting server...")
        await server.start()
        
        # Keep the server running until interrupted
        if server.mcp_protocol == 'streamable_http':
            if not hasattr(server, '_started_mcp_server_instance') or server._started_mcp_server_instance is None:
                raise RuntimeError("HTTP server instance not found after start")
            
            logger.info(f"Server is running on port {server.config.get('http', {}).get('port', 8080)}. Press Ctrl+C to stop.")
            try:
                # Keep the server running until interrupted
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info("Server shutdown requested")
            except KeyboardInterrupt:
                logger.info("Server stopped by user")
        else:  # stdio protocol
            logger.info("Server is running in stdio mode. Press Ctrl+C to stop.")
            try:
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info("Server shutdown requested")
            except KeyboardInterrupt:
                logger.info("Server stopped by user")
        
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        raise
    finally:
        if server is not None:
            logger.info("Shutting down server...")
            await server.stop()

if __name__ == "__main__":
    import json
    import sys
    import os
    
    # Parse command line arguments first
    mcp_protocol = None
    default_config_path = os.path.join('odoo_mcp', 'config', 'config.json')
    config_path = default_config_path
    
    if len(sys.argv) > 1:
        if sys.argv[1] in ['streamable_http', 'stdio']:
            mcp_protocol = sys.argv[1]
            if len(sys.argv) > 2:
                config_path = sys.argv[2]
        else:
            config_path = sys.argv[1]
    
    # Load configuration first, using print to stderr for any errors
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        if config_path != default_config_path:
            print(f"Configuration file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"Using default configuration file: {default_config_path}", file=sys.stderr)
            try:
                with open(default_config_path, 'r') as f:
                    config = json.load(f)
            except FileNotFoundError:
                print(f"Default configuration file not found: {default_config_path}", file=sys.stderr)
                print("Please create a configuration file or specify a valid path", file=sys.stderr)
                sys.exit(1)
    except json.JSONDecodeError:
        print(f"Invalid JSON in configuration file: {config_path}", file=sys.stderr)
        sys.exit(1)
    
    # Set MCP protocol in config if specified
    if mcp_protocol:
        config['connection_type'] = mcp_protocol
    
    # Now that we have the config, import and setup logging
    from odoo_mcp.core.logging_config import setup_logging
    setup_logging(config.get('log_level', 'INFO'), config.get('connection_type', 'stdio'))
    
    # Now we can use logger for the rest of the operations
    logger = logging.getLogger(__name__)
    
    try:
        # Run server
        logger.info("Initializing server...")
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        sys.exit(1) 