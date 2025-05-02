"""
Odoo MCP Server SDK implementation.
This module provides the main server implementation for Odoo MCP.
"""

import logging
import asyncio
from typing import Dict, Any, Optional, List, Union
from fastmcp import FastMCP, MCPRequest, MCPResponse
from fastmcp.decorators import mcp_handler, mcp_resource, mcp_tool

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
from odoo_mcp.error_handling.exceptions import (
    OdooMCPError, AuthError, NetworkError, ProtocolError,
    ConfigurationError, ConnectionError, SessionError,
    OdooValidationError, OdooRecordNotFoundError, PoolTimeoutError,
    RateLimitError, ResourceError, ToolError, PromptError,
    CacheError, BusError
)

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
        self.app = FastMCP()
        
        # Initialize components
        initialize_connection_pool(config)
        initialize_authenticator(config)
        initialize_session_manager(config)
        initialize_rate_limiter(config)
        initialize_cache_manager(config)
        initialize_prompt_manager(config)
        initialize_resource_manager(config)
        initialize_tool_manager(config)
        
        # Get manager instances
        self.connection_pool = get_connection_pool()
        self.authenticator = get_authenticator()
        self.session_manager = get_session_manager()
        self.rate_limiter = get_rate_limiter()
        self.cache_manager = get_cache_manager()
        self.prompt_manager = get_prompt_manager()
        self.resource_manager = get_resource_manager()
        self.tool_manager = get_tool_manager()
        
        # Register handlers
        self._register_handlers()
        
        logger.info("Odoo MCP Server initialized")

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

    async def start(self) -> None:
        """Start the MCP server."""
        try:
            await self.app.start(
                host=self.config.get('host', 'localhost'),
                port=self.config.get('port', 8000)
            )
            logger.info("Odoo MCP Server started")
        except Exception as e:
            logger.error(f"Error starting server: {str(e)}")
            raise

    async def stop(self) -> None:
        """Stop the MCP server."""
        try:
            await self.app.stop()
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
    server = create_server(config)
    await server.start()
    
    try:
        # Keep the server running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await server.stop()

if __name__ == "__main__":
    import json
    import sys
    
    # Load configuration
    with open(sys.argv[1] if len(sys.argv) > 1 else 'config.json', 'r') as f:
        config = json.load(f)
    
    # Configure logging
    logging.basicConfig(
        level=config.get('log_level', 'INFO'),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run server
    asyncio.run(run_server(config)) 