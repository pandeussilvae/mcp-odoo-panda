"""
Odoo MCP Server SDK implementation.
This module provides the main server implementation for Odoo MCP.
"""

import logging
import asyncio
from typing import Dict, Any, Optional, List, Union
from fastmcp import FastMCP, MCPRequest, MCPResponse
from fastmcp.decorators import mcp_handler, mcp_resource, mcp_tool
from aiohttp import web
import json

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

# Constants
SERVER_NAME = "odoo-mcp-server"
SERVER_VERSION = "2024.2.5"  # Using CalVer: YYYY.MM.DD
PROTOCOL_VERSION = "2024-11-05"  # MCP protocol version

logger = logging.getLogger(__name__)

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
            
            # Create MCP request with correct parameters
            mcp_request = MCPRequest(
                method=data.get('method'),
                parameters=data.get('parameters', {}),
                id=data.get('id')
            )
            
            # List of methods that don't require authentication
            no_auth_methods = {
                'initialize',
                'list_resources',
                'list_tools',
                'list_prompts',
                'get_prompt'
            }
            
            # Route the request to the appropriate handler based on the request type
            if mcp_request.method in no_auth_methods:
                # Handle methods that don't require authentication
                if mcp_request.method == 'initialize':
                    if not hasattr(self, 'capabilities_manager'):
                        logger.error("CapabilitiesManager not initialized")
                        return web.json_response({
                            'jsonrpc': '2.0',
                            'error': {
                                'code': -32603,
                                'message': 'Server not properly initialized'
                            },
                            'id': mcp_request.id
                        }, status=500)
                    response = await self._handle_initialize(mcp_request)
                elif mcp_request.method == 'list_resources':
                    response = await self._handle_list_resources(mcp_request)
                elif mcp_request.method == 'list_tools':
                    response = await self._handle_list_tools(mcp_request)
                elif mcp_request.method == 'list_prompts':
                    response = await self._handle_list_prompts(mcp_request)
                elif mcp_request.method == 'get_prompt':
                    response = await self._handle_get_prompt(mcp_request)
            else:
                # For all other methods, validate session first
                session = await self._validate_session(mcp_request)
                if not session:
                    return web.json_response({
                        'jsonrpc': '2.0',
                        'error': {
                            'code': -32001,
                            'message': 'Invalid session'
                        },
                        'id': mcp_request.id
                    }, status=401)
                
                # Route to appropriate handler based on request type
                if mcp_request.resource:
                    response = await self.handle_resource(mcp_request)
                elif mcp_request.tool:
                    response = await self.handle_tool(mcp_request)
                else:
                    response = await self.handle_default(mcp_request)
            
            # Convert MCPResponse to JSON-RPC response
            response_dict = {
                'jsonrpc': '2.0',
                'id': mcp_request.id
            }
            
            if response.success:
                response_dict['result'] = response.data
            else:
                response_dict['error'] = {
                    'code': -32000,
                    'message': response.error
                }
            
            # Return response
            return web.json_response(response_dict)
            
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
            resources = self.capabilities_manager.list_resources()
            return MCPResponse.success({'resources': resources})
        except Exception as e:
            logger.error(f"Error handling list_resources request: {str(e)}")
            return MCPResponse.error(str(e))

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
                # For stdio protocol, just start
                await self.app.start()
                logger.info("Odoo MCP Server started successfully in stdio mode")
            
        except Exception as e:
            logger.error(f"Error starting server: {str(e)}")
            raise

    async def stop(self) -> None:
        """Stop the MCP server."""
        try:
            logger.info("Stopping Odoo MCP Server...")
            if hasattr(self, '_started_mcp_server_instance') and self._started_mcp_server_instance is not None:
                await self._started_mcp_server_instance.stop()
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
    
    # Parse command line arguments
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
    
    # Load configuration
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        if config_path != default_config_path:
            logger.error(f"Configuration file not found: {config_path}")
            sys.exit(1)
        else:
            logger.info(f"Using default configuration file: {default_config_path}")
            try:
                with open(default_config_path, 'r') as f:
                    config = json.load(f)
            except FileNotFoundError:
                logger.error(f"Default configuration file not found: {default_config_path}")
                logger.error("Please create a configuration file or specify a valid path")
                sys.exit(1)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in configuration file: {config_path}")
        sys.exit(1)
    
    # Set MCP protocol in config if specified
    if mcp_protocol:
        config['connection_type'] = mcp_protocol
    
    # Configure logging
    logging.basicConfig(
        level=config.get('log_level', 'INFO'),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        # Run server
        logger.info("Initializing server...")
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        sys.exit(1) 