"""
Odoo MCP Server SDK implementation.
This module provides the main server implementation for Odoo MCP.
"""

import sys
import os
import json
from datetime import datetime

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
from odoo_mcp.core.logging_config import setup_logging, setup_logging_from_config

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

# Utility per risposta errore JSON-RPC con id corretto

def make_jsonrpc_error(id, code, message):
    # Ensure id is never None
    if id is None:
        id = 0
    return {
        "jsonrpc": "2.0",
        "id": id,
        "error": {
            "code": code,
            "message": message
        }
    }

class OdooMCPServer:
    """Main Odoo MCP Server implementation."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the Odoo MCP Server.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self._initialized = False
        
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
            self.web_app = web.Application()
            self.web_app.router.add_post('/', self._handle_http_request)
            self.web_app.router.add_post('/mcp', self._handle_chunked_streaming)
            self.web_app.router.add_get('/sse', self._handle_sse_request)
        elif self.mcp_protocol == 'http':
            self.config['http'] = self.config.get('http', {})
            self.web_app = web.Application()
            self.web_app.router.add_post('/', self._handle_http_request)
            self.web_app.router.add_post('/mcp', self._handle_http_post)
        
        # Select handler class based on Odoo protocol
        handler_class = JSONRPCHandler if self.odoo_protocol == 'jsonrpc' else XMLRPCHandler
        
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

    def _serialize_response(self, response: Any, request_id: Union[str, int]) -> Dict[str, Any]:
        """Serialize a response to a JSON-RPC compatible dictionary."""
        response_dict = {
            'jsonrpc': '2.0',
            'id': request_id if request_id is not None else 0,
            'method': 'response'  # Add method field as required by Zod schema
        }
        
        if isinstance(response, dict):
            # If response is already a dictionary, use it directly
            if 'jsonrpc' in response:
                response_dict.update(response)
            else:
                response_dict['result'] = response
        elif hasattr(response, 'success'):
            # If response is an MCPResponse object
            if response.success:
                response_dict['result'] = response.data
            else:
                response_dict['error'] = {
                    'code': -32000,
                    'message': response.error
                }
        elif hasattr(response, 'model_dump'):
            # If response is a Pydantic model
            response_dict['result'] = response.model_dump()
        elif hasattr(response, 'jsonrpc'):
            # If response is a JsonRpcResponse
            response_dict.update({
                'id': response.id if response.id is not None else request_id,
                'method': response.method if hasattr(response, 'method') else 'response'
            })
            if hasattr(response, 'result'):
                response_dict['result'] = response.result
            if hasattr(response, 'error'):
                response_dict['error'] = response.error
        else:
            # If response is neither, treat it as an error
            response_dict['error'] = {
                'code': -32603,
                'message': 'Invalid response format'
            }
        
        return response_dict

    async def _handle_http_request(self, request: web.Request, data=None) -> web.Response:
        """Handle HTTP requests."""
        try:
            # Parse request data
            if data is None:
                data = await request.json()
            
            # Extract request details
            method = data.get('method')
            request_id = data.get('id', 0)  # Default to 0 if no id
            params = data.get('params', {})
            
            # Create MCP request
            mcp_request = MCPRequest(
                method=method,
                parameters=params,
                id=request_id,
                headers=dict(request.headers)
            )
            
            # Process request
            response = await self._process_mcp_request(mcp_request)
            
            # Serialize response
            response_dict = self._serialize_response(response, request_id)
            
            # Return JSON response
            return web.json_response(response_dict)
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in request: {str(e)}")
            return web.json_response({
                'jsonrpc': '2.0',
                'id': request_id if 'request_id' in locals() else 0,
                'method': 'error',
                'error': {
                    'code': -32700,
                    'message': 'Parse error: Invalid JSON'
                }
            }, status=400)
        except Exception as e:
            logger.error(f"Error handling request: {str(e)}")
            return web.json_response({
                'jsonrpc': '2.0',
                'id': request_id if 'request_id' in locals() else 0,
                'method': 'error',
                'error': {
                    'code': -32603,
                    'message': str(e)
                }
            }, status=500)

    async def initialize(self) -> None:
        """Initialize the server and its components."""
        if self._initialized:
            return

        try:
            # Initialize FastMCP
            await self.app.initialize()
            
            # Initialize capabilities manager if not already initialized
            if not hasattr(self, 'capabilities_manager'):
                self.capabilities_manager = CapabilitiesManager(self.config)
            
            self._initialized = True
            logger.info("Server initialized successfully")
                except Exception as e:
            logger.error(f"Error initializing server: {str(e)}")
            raise

    async def start(self) -> None:
        """Start the server."""
        if not self._initialized:
            await self.initialize()

        try:
            if self.mcp_protocol == 'streamable_http':
                runner = web.AppRunner(self.web_app)
                await runner.setup()
                site = web.TCPSite(runner, self.config.get('http', {}).get('host', '0.0.0.0'),
                                 self.config.get('http', {}).get('port', 8080))
                await site.start()
                self._started_mcp_server_instance = runner
                logger.info(f"HTTP server started on {self.config.get('http', {}).get('host', '0.0.0.0')}:{self.config.get('http', {}).get('port', 8080)}")
            else:
                # Start FastMCP server
                await self.app.start()
                logger.info("FastMCP server started")
        except Exception as e:
            logger.error(f"Error starting server: {str(e)}")
            raise

    async def stop(self) -> None:
        """Stop the server."""
        try:
            if self.mcp_protocol == 'streamable_http' and hasattr(self, '_started_mcp_server_instance'):
                await self._started_mcp_server_instance.cleanup()
            else:
                await self.app.stop()
            logger.info("Server stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping server: {str(e)}")
            raise

    async def _handle_initialize(self, request: MCPRequest) -> Dict[str, Any]:
        """Handle initialize request."""
        logger.debug(f"_handle_initialize called. Self: {self}, Type: {type(self)}, CapabilitiesManager: {getattr(self, 'capabilities_manager', None)}")
        try:
            if not hasattr(self, 'capabilities_manager'):
                logger.error("CapabilitiesManager not initialized in _handle_initialize")
                return {
                    'jsonrpc': '2.0',
                    'error': {
                        'code': -32603,
                        'message': 'Server not properly initialized'
                    },
                    'id': request.id if request.id is not None else 0
                }
            
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
            
            # Return the response data directly as a dictionary
            return {
                'jsonrpc': '2.0',
                'id': request.id if request.id is not None else 0,
                'result': response_data
            }
            
        except Exception as e:
            logger.error(f"Error handling initialize request: {str(e)}")
            return {
                'jsonrpc': '2.0',
                'error': {
                    'code': -32603,
                    'message': str(e)
                },
                'id': request.id if request.id is not None else 0
            }

    async def _handle_list_resources(self, request: MCPRequest) -> Dict[str, Any]:
        """Handle list_resources request."""
        try:
            # Get list of resources from capabilities manager
            resources = self.capabilities_manager.list_resources()
            
            # Log the response for debugging
            logger.debug(f"List resources response: {json.dumps(resources, indent=2)}")
            
            # Return a properly formatted JSON-RPC response
            return {
                'jsonrpc': '2.0',
                'id': request.id if request.id is not None else 0,
                'result': {
                    'resources': resources
                }
            }
        except Exception as e:
            logger.error(f"Error listing resources: {str(e)}")
            return {
                'jsonrpc': '2.0',
                'id': request.id if request.id is not None else 0,
                'error': {
                    'code': -32603,
                    'message': str(e)
                }
            }

    async def _handle_list_prompts(self, request: MCPRequest) -> Dict[str, Any]:
        """Handle list_prompts request."""
        try:
            # Get list of prompts from capabilities manager
            prompts = self.capabilities_manager.list_prompts()
            
            # Log the response for debugging
            logger.debug(f"List prompts response: {json.dumps(prompts, indent=2)}")
            
            # Return a properly formatted JSON-RPC response
            return {
                'jsonrpc': '2.0',
                'id': request.id if request.id is not None else 0,
                'result': {
                    'prompts': prompts
                }
            }
        except Exception as e:
            logger.error(f"Error handling list_prompts request: {str(e)}")
            return {
                'jsonrpc': '2.0',
                'id': request.id if request.id is not None else 0,
                'error': {
                    'code': -32603,
                    'message': str(e)
                }
            }

    async def _handle_get_prompt(self, request: MCPRequest) -> Dict[str, Any]:
        """Handle get_prompt request."""
        try:
            name = request.parameters.get('name')
            args = request.parameters.get('arguments', {})
            
            prompt = self.capabilities_manager.get_prompt(name)
            if not prompt:
                return {
                    'jsonrpc': '2.0',
                    'id': request.id if request.id is not None else 0,
                    'error': {
                        'code': -32602,
                        'message': f'Prompt not found: {name}'
                    }
                }
            
            # Convert Prompt object to dictionary
            prompt_dict = {
                "name": prompt.name,
                "description": prompt.description,
                "template": prompt.template,
                "parameters": prompt.parameters
            }
            
            # Create response with required messages array
            return {
                'jsonrpc': '2.0',
                'id': request.id if request.id is not None else 0,
                'result': {
                "prompt": prompt_dict,
                "messages": []  # Add empty messages array as required
            }
            }
        except Exception as e:
            logger.error(f"Error handling get_prompt request: {str(e)}")
            return {
                'jsonrpc': '2.0',
                'id': request.id if request.id is not None else 0,
                'error': {
                    'code': -32603,
                    'message': str(e)
                }
            }

    async def _handle_create_session(self, request: MCPRequest) -> Dict[str, Any]:
        """Handle create_session request."""
        try:
            # Create a new session
            session = await self.session_manager.create_session()
            
            # Return a properly formatted JSON-RPC response
            return {
                'jsonrpc': '2.0',
                'id': request.id if request.id is not None else 0,
                'result': {
                    'session_id': session.id
                }
            }
            except Exception as e:
                logger.error(f"Error creating session: {str(e)}")
            return {
                'jsonrpc': '2.0',
                'id': request.id if request.id is not None else 0,
                'error': {
                    'code': -32603,
                    'message': str(e)
                }
            }

    async def _handle_login(self, request: MCPRequest) -> Dict[str, Any]:
        """Handle login request."""
        try:
            # Extract credentials from parameters
            credentials = request.parameters.get('credentials', {})
            if not credentials:
                logger.error("No credentials provided in login request")
                return {
                    'jsonrpc': '2.0',
                    'id': request.id if request.id is not None else 0,
                    'error': {
                        'code': -32602,
                        'message': "No credentials provided"
                    }
                }
            
            # Validate required credential fields
            required_fields = ['username', 'password', 'database']
            missing_fields = [field for field in required_fields if field not in credentials]
            if missing_fields:
                logger.error(f"Missing required credential fields: {missing_fields}")
                return {
                    'jsonrpc': '2.0',
                    'id': request.id if request.id is not None else 0,
                    'error': {
                        'code': -32602,
                        'message': f"Missing required credential fields: {', '.join(missing_fields)}"
                    }
                }
            
            # Authenticate with Odoo
            try:
                auth_result = await self.authenticator.authenticate(credentials)
                if not auth_result:
                    logger.error("Authentication failed in login")
                    return {
                        'jsonrpc': '2.0',
                        'id': request.id if request.id is not None else 0,
                        'error': {
                            'code': -32603,
                            'message': "Authentication failed"
                        }
                    }
            except AuthError as e:
                logger.error(f"Authentication error in login: {str(e)}")
                return {
                    'jsonrpc': '2.0',
                    'id': request.id if request.id is not None else 0,
                    'error': {
                        'code': -32603,
                        'message': str(e)
                    }
                }
            
            # Create MCP session
            try:
                session = await self.session_manager.create_session(credentials)
                if not session:
                    logger.error("Failed to create session after login")
                    return {
                        'jsonrpc': '2.0',
                        'id': request.id if request.id is not None else 0,
                        'error': {
                            'code': -32603,
                            'message': "Failed to create session"
                        }
                    }
                logger.info(f"Login successful, session created: {session['id']}")
                # Return session information
                return {
                    'jsonrpc': '2.0',
                    'id': request.id if request.id is not None else 0,
                    'result': {
                    'session': {
                        'id': session['id'],
                        'expires_at': session['expires_at']
                    }
                    }
                }
        except Exception as e:
                logger.error(f"Error creating session after login: {str(e)}")
                return {
                'jsonrpc': '2.0',
                    'id': request.id if request.id is not None else 0,
                'error': {
                    'code': -32603,
                        'message': f"Failed to create session: {str(e)}"
                    }
                }
                except Exception as e:
            logger.error(f"Unexpected error in login: {str(e)}")
            return {
                        'jsonrpc': '2.0',
                'id': request.id if request.id is not None else 0,
                        'error': {
                            'code': -32603,
                    'message': f"Unexpected error: {str(e)}"
                }
            }

    async def handle_request(self, request: MCPRequest) -> Dict[str, Any]:
        """Handle incoming MCP request."""
        try:
            # Get the appropriate handler for the request method
            handler = self._get_handler(request.method)
            if not handler:
                        return {
                            'jsonrpc': '2.0',
                    'id': request.id if request.id is not None else 0,
                        'error': {
                            'code': -32601,
                            'message': f'Method not found: {request.method}'
                    }
                }
            
            # Call the handler
            response = await handler(request)
            
            # If response is already a dictionary, return it
            if isinstance(response, dict):
                return response
            
            # Otherwise, convert MCPResponse to dictionary
            if response.success:
                    return {
                        'jsonrpc': '2.0',
                    'id': request.id if request.id is not None else 0,
                    'result': response.data
                }
            else:
                    return {
                        'jsonrpc': '2.0',
                    'id': request.id if request.id is not None else 0,
                        'error': {
                            'code': -32603,
                    'message': response.error
                }
                }
        except Exception as e:
            logger.error(f"Error handling request: {str(e)}")
            return {
                'jsonrpc': '2.0',
                'id': request.id if request.id is not None else 0,
                'error': {
                    'code': -32603,
                    'message': str(e)
                }
            }

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
        
        # Initialize and start server
        logger.info("Initializing and starting server...")
        await server.initialize()
        await server.start()
        
        # Now that we have the config, import and setup logging
        if 'logging' in config:
            setup_logging_from_config(config['logging'])
        else:
            setup_logging(config.get('log_level', 'INFO'), config.get('connection_type', 'stdio'))
        
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

def override_config_with_env(config):
    """
    Override configuration values with environment variables.
    
    Args:
        config: The configuration dictionary to override
        
    Returns:
        The updated configuration dictionary
    """
    # Odoo connection settings
    if os.getenv('ODOO_URL'):
        config['odoo_url'] = os.getenv('ODOO_URL')
    if os.getenv('ODOO_DB'):
        config['database'] = os.getenv('ODOO_DB')
    if os.getenv('ODOO_USER'):
        config['username'] = os.getenv('ODOO_USER')
    if os.getenv('ODOO_PASSWORD'):
        config['api_key'] = os.getenv('ODOO_PASSWORD')
    
    # MCP server settings
    if os.getenv('PROTOCOL'):
        config['protocol'] = os.getenv('PROTOCOL')
    if os.getenv('CONNECTION_TYPE'):
        config['connection_type'] = os.getenv('CONNECTION_TYPE')
    if os.getenv('LOGGING_LEVEL'):
        config['log_level'] = os.getenv('LOGGING_LEVEL')
    
    # Advanced settings
    if os.getenv('REQUESTS_PER_MINUTE'):
        config['requests_per_minute'] = int(os.getenv('REQUESTS_PER_MINUTE'))
    if os.getenv('POOL_SIZE'):
        config['pool_size'] = int(os.getenv('POOL_SIZE'))
    if os.getenv('TIMEOUT'):
        config['timeout'] = int(os.getenv('TIMEOUT'))
    if os.getenv('SESSION_TIMEOUT_MINUTES'):
        config['session_timeout_minutes'] = int(os.getenv('SESSION_TIMEOUT_MINUTES'))
    
    # HTTP settings
    if 'http' not in config:
        config['http'] = {}
    if os.getenv('HTTP_HOST'):
        config['http']['host'] = os.getenv('HTTP_HOST')
    if os.getenv('HTTP_PORT'):
        config['http']['port'] = int(os.getenv('HTTP_PORT'))
    if os.getenv('HTTP_STREAMABLE'):
        config['http']['streamable'] = os.getenv('HTTP_STREAMABLE').lower() == 'true'
    
    # Log the final config after override
    logger.debug(f"Final config after override: {config}")
    
    return config

if __name__ == "__main__":
    import json
    import sys
    import os
    import asyncio
    
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
    
    # OVERRIDE: aggiorna config con variabili d'ambiente
    config = override_config_with_env(config)
    
    # Now we can use logger for the rest of the operations
    logger = logging.getLogger(__name__)
    
    async def main():
        """Main async entry point."""
    try:
            # Create and run server
        logger.info("Initializing server...")
            server = create_server(config)
            
            # Initialize server components
            logger.info("Initializing server components...")
            await server.initialize()
            
            # Start server
            logger.info("Starting server...")
            await server.start()
            
            # Keep the server running
            try:
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info("Server shutdown requested")
            except KeyboardInterrupt:
                logger.info("Server stopped by user")
            
        except Exception as e:
            logger.error(f"Server error: {str(e)}")
            sys.exit(1)
        finally:
            if 'server' in locals():
                logger.info("Shutting down server...")
                await server.stop()
    
    try:
        # Run the async main function
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        sys.exit(1) 