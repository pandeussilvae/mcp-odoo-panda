"""
Odoo MCP Server implementation.
This module implements the MCP server for Odoo integration.
"""

import asyncio
import logging
import signal
from typing import Dict, Any, Optional, Type, Union, List, Callable, Set
import yaml
from datetime import datetime
import argparse
import contextlib

# Import core components
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler
from odoo_mcp.core.jsonrpc_handler import JSONRPCHandler
from odoo_mcp.connection.connection_pool import ConnectionPool
from odoo_mcp.authentication.authenticator import OdooAuthenticator
from odoo_mcp.connection.session_manager import SessionManager
from odoo_mcp.security.utils import RateLimiter, mask_sensitive_data
from odoo_mcp.error_handling.exceptions import OdooMCPError, ConfigurationError, ProtocolError, AuthError, NetworkError
from odoo_mcp.core.logging_config import setup_logging
from odoo_mcp.performance.caching import cache_manager, CACHE_TYPE
from odoo_mcp.core.bus_handler import OdooBusHandler

# Import MCP components
from mcp_local_backup import (
    Server, Resource, Tool, Prompt,
    ServerInfo, ClientInfo, ResourceTemplate,
    GetPromptResult, PromptMessage, TextContent,
    ResourceType, StdioProtocol, SSEProtocol
)

logger = logging.getLogger(__name__)

class OdooMCPServer(Server):
    """
    Odoo MCP Server implementation.
    """
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the Odoo MCP Server.

        Args:
            config: The loaded server configuration dictionary.
        """
        super().__init__("odoo-mcp-server", "1.0.0")
        self.config = config
        self.protocol_type = config.get('protocol', 'xmlrpc').lower()
        self.connection_type = config.get('connection_type', 'stdio').lower()
        
        # Initialize core components
        self.pool = ConnectionPool(config, self._get_handler_class())
        self.authenticator = OdooAuthenticator(config, self.pool)
        self.session_manager = SessionManager(config, self.authenticator, self.pool)
        self.rate_limiter = RateLimiter(
            requests_per_minute=config.get('requests_per_minute', 120),
            max_wait_seconds=config.get('rate_limit_max_wait_seconds', None)
        )

        # Initialize protocol handler
        if self.connection_type == 'stdio':
            self.protocol = StdioProtocol(self._handle_request)
        elif self.connection_type == 'sse':
            self.protocol = SSEProtocol(
                self._handle_request,
                allowed_origins=set(config.get('allowed_origins', ['*']))
            )
        else:
            raise ConfigurationError(f"Unsupported connection type: {self.connection_type}")

        # Initialize bus handler
        self.bus_handler = OdooBusHandler(config, self._notify_resource_update)

    def _get_handler_class(self) -> Union[Type[XMLRPCHandler], Type[JSONRPCHandler]]:
        """Get the appropriate handler class based on protocol type."""
        if self.protocol_type == 'xmlrpc':
            return XMLRPCHandler
        elif self.protocol_type == 'jsonrpc':
            return JSONRPCHandler
        else:
            raise ConfigurationError(f"Unsupported protocol type: {self.protocol_type}")

    @property
    def capabilities(self) -> Dict[str, Any]:
        """Get server capabilities."""
        return {
            "resources": {
                "templates": [
                    {
                        "uriTemplate": "odoo://{model}/{id}",
                        "name": "Odoo Record",
                        "description": "Represents a single record in an Odoo model.",
                        "mimeType": "application/json"
                    },
                    {
                        "uriTemplate": "odoo://{model}/list",
                        "name": "Odoo Record List",
                        "description": "Represents a list of records in an Odoo model.",
                        "mimeType": "application/json"
                    },
                    {
                        "uriTemplate": "odoo://{model}/binary/{field}/{id}",
                        "name": "Odoo Binary Field",
                        "description": "Represents a binary field value from an Odoo record.",
                        "mimeType": "application/octet-stream"
                    }
                ]
            },
            "tools": {
                "odoo_search_read": {},
                "odoo_read": {},
                "odoo_create": {},
                "odoo_write": {},
                "odoo_unlink": {},
                "odoo_call_method": {}
            },
            "prompts": {
                "analyze-record": {},
                "create-record": {},
                "update-record": {},
                "advanced-search": {},
                "call-method": {}
            }
        }

    async def initialize(self, client_info: ClientInfo) -> ServerInfo:
        """Handle initialization request."""
        return ServerInfo(
            name="odoo-mcp-server",
            version="1.0.0",
            capabilities=self.capabilities
        )

    async def get_resource(self, uri: str) -> Resource:
        """Get a resource by URI."""
        # Parse URI
        if not uri.startswith("odoo://"):
            raise ProtocolError(f"Invalid URI scheme: {uri}")
        
        parts = uri[len("odoo://"):].split('/')
        if len(parts) < 2:
            raise ProtocolError(f"Invalid URI format: {uri}")

        # Get authentication details
        auth_details = await self._get_odoo_auth(self.session_manager, self.config, {})

        # Handle different resource types
        if parts[1] == "list":
            # List of records
            model_name = parts[0]
            data = await self._handle_list_resource(model_name, auth_details)
            return Resource(
                uri=uri,
                type=ResourceType.LIST,
                data=data,
                mime_type="application/json"
            )
        elif parts[1] == "binary":
            # Binary field
            if len(parts) != 4:
                raise ProtocolError(f"Invalid binary field URI format: {uri}")
            model_name, _, field_name, id_str = parts
            data = await self._handle_binary_resource(model_name, field_name, id_str, auth_details)
            return Resource(
                uri=uri,
                type=ResourceType.BINARY,
                data=data,
                mime_type="application/octet-stream"
            )
        else:
            # Single record
            if len(parts) != 2:
                raise ProtocolError(f"Invalid record URI format: {uri}")
            model_name, id_str = parts
            data = await self._handle_record_resource(model_name, id_str, auth_details)
            return Resource(
                uri=uri,
                type=ResourceType.RECORD,
                data=data,
                mime_type="application/json"
            )

    async def list_resources(self, template: Optional[ResourceTemplate] = None) -> List[Resource]:
        """List available resources."""
        return [
            Resource(
                uri="odoo://{model}/{id}",
                type=ResourceType.RECORD,
                data=None,
                mime_type="application/json"
            ),
            Resource(
                uri="odoo://{model}/list",
                type=ResourceType.LIST,
                data=None,
                mime_type="application/json"
            ),
            Resource(
                uri="odoo://{model}/binary/{field}/{id}",
                type=ResourceType.BINARY,
                data=None,
                mime_type="application/octet-stream"
            )
        ]

    async def list_tools(self) -> List[Tool]:
        """List available tools."""
        return [
            Tool(
                name="odoo_search_read",
                description="Search and read Odoo records",
                input_schema={
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "domain": {"type": "array"},
                        "fields": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer", "default": 80},
                        "offset": {"type": "integer", "default": 0},
                        "context": {"type": "object", "default": {}}
                    },
                    "required": ["model"]
                }
            ),
            Tool(
                name="odoo_read",
                description="Read specific fields for given Odoo record IDs",
                input_schema={
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "ids": {"type": "array", "items": {"type": "integer"}},
                        "fields": {"type": "array", "items": {"type": "string"}},
                        "context": {"type": "object", "default": {}}
                    },
                    "required": ["model", "ids"]
                }
            ),
            Tool(
                name="odoo_create",
                description="Create a new record in an Odoo model",
                input_schema={
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "values": {"type": "object"},
                        "context": {"type": "object", "default": {}}
                    },
                    "required": ["model", "values"]
                }
            ),
            Tool(
                name="odoo_write",
                description="Update existing Odoo records",
                input_schema={
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "ids": {"type": "array", "items": {"type": "integer"}},
                        "values": {"type": "object"},
                        "context": {"type": "object", "default": {}}
                    },
                    "required": ["model", "ids", "values"]
                }
            ),
            Tool(
                name="odoo_unlink",
                description="Delete Odoo records",
                input_schema={
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "ids": {"type": "array", "items": {"type": "integer"}},
                        "context": {"type": "object", "default": {}}
                    },
                    "required": ["model", "ids"]
                }
            ),
            Tool(
                name="odoo_call_method",
                description="Call a specific method on Odoo records",
                input_schema={
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "method": {"type": "string"},
                        "ids": {"type": "array", "items": {"type": "integer"}},
                        "args": {"type": "array", "default": []},
                        "kwargs": {"type": "object", "default": {}},
                        "context": {"type": "object", "default": {}}
                    },
                    "required": ["model", "method", "ids"]
                }
            )
        ]

    async def list_prompts(self) -> List[Prompt]:
        """List available prompts."""
        return [
            Prompt(
                name="analyze-record",
                description="Analyze an Odoo record and provide insights",
                arguments=[
                    {
                        "name": "uri",
                        "description": "URI of the record to analyze (e.g., odoo://res.partner/123)",
                        "required": True
                    }
                ]
            ),
            Prompt(
                name="create-record",
                description="Create a new record with guided field selection",
                arguments=[
                    {
                        "name": "model",
                        "description": "Odoo model name (e.g., res.partner)",
                        "required": True
                    },
                    {
                        "name": "template",
                        "description": "Optional template to pre-fill fields",
                        "required": False
                    }
                ]
            ),
            Prompt(
                name="update-record",
                description="Update an existing record with guided field selection",
                arguments=[
                    {
                        "name": "uri",
                        "description": "URI of the record to update (e.g., odoo://res.partner/123)",
                        "required": True
                    }
                ]
            ),
            Prompt(
                name="advanced-search",
                description="Perform an advanced search with domain builder",
                arguments=[
                    {
                        "name": "model",
                        "description": "Odoo model name (e.g., res.partner)",
                        "required": True
                    },
                    {
                        "name": "fields",
                        "description": "Fields to return in results",
                        "required": False
                    }
                ]
            ),
            Prompt(
                name="call-method",
                description="Call a method on records with guided parameter selection",
                arguments=[
                    {
                        "name": "uri",
                        "description": "URI of the record (e.g., odoo://res.partner/123) or model name for model methods",
                        "required": True
                    },
                    {
                        "name": "method",
                        "description": "Name of the method to call",
                        "required": True
                    }
                ]
            )
        ]

    async def get_prompt(self, name: str, args: Dict[str, Any]) -> GetPromptResult:
        """Get a prompt by name."""
        # Find the prompt
        prompt = next((p for p in await self.list_prompts() if p.name == name), None)
        if not prompt:
            raise ProtocolError(f"Prompt not found: {name}")

        # Handle different prompt types
        if name == "analyze-record":
            return await self._handle_analyze_record_prompt(prompt, args)
        elif name == "create-record":
            return await self._handle_create_record_prompt(prompt, args)
        elif name == "update-record":
            return await self._handle_update_record_prompt(prompt, args)
        elif name == "advanced-search":
            return await self._handle_advanced_search_prompt(prompt, args)
        elif name == "call-method":
            return await self._handle_call_method_prompt(prompt, args)
        else:
            raise ProtocolError(f"Unsupported prompt type: {name}")

    async def run(self):
        """Run the server."""
        if self.connection_type == 'stdio':
            print("[MCP] Server avviato in modalità STDIO (comunicazione tramite stdin/stdout)")
            await self.protocol.run()
        elif self.connection_type == 'sse':
            host = self.config.get('host', 'localhost')
            port = self.config.get('port', 8080)
            print(f"[MCP] Server avviato in modalità SSE su http://{host}:{port}")
            await self.protocol.run(host=host, port=port)

    async def stop(self):
        """Stop the server."""
        self.protocol.stop()
        await super().stop()

    def _handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle incoming requests."""
        try:
            # Validate request format
            if not isinstance(request, dict):
                raise ValueError("Request must be a JSON object")

            # Extract method and parameters
            method = request.get('method')
            params = request.get('params', {})
            request_id = request.get('id')

            # Handle different methods
            if method == 'initialize':
                client_info = ClientInfo.from_dict(params)
                server_info = asyncio.run(self.initialize(client_info))
                return {
                    'jsonrpc': '2.0',
                    'result': server_info.__dict__,
                    'id': request_id
                }
            elif method == 'get_resource':
                resource = asyncio.run(self.get_resource(params['uri']))
                return {
                    'jsonrpc': '2.0',
                    'result': resource.__dict__,
                    'id': request_id
                }
            elif method == 'list_resources':
                resources = asyncio.run(self.list_resources())
                return {
                    'jsonrpc': '2.0',
                    'result': [r.__dict__ for r in resources],
                    'id': request_id
                }
            elif method == 'list_tools':
                tools = asyncio.run(self.list_tools())
                return {
                    'jsonrpc': '2.0',
                    'result': [t.__dict__ for t in tools],
                    'id': request_id
                }
            elif method == 'list_prompts':
                prompts = asyncio.run(self.list_prompts())
                return {
                    'jsonrpc': '2.0',
                    'result': [p.__dict__ for p in prompts],
                    'id': request_id
                }
            elif method == 'get_prompt':
                result = asyncio.run(self.get_prompt(params['name'], params.get('args', {})))
                return {
                    'jsonrpc': '2.0',
                    'result': result.__dict__,
                    'id': request_id
                }
            else:
                raise ProtocolError(f"Unknown method: {method}")

        except Exception as e:
            logger.error(f"Error handling request: {e}")
            return {
                'jsonrpc': '2.0',
                'error': {
                    'code': -32603,
                    'message': str(e)
                },
                'id': request_id
            }

    async def _handle_list_resource(self, model_name: str, auth_details: Dict[str, Any]) -> Dict[str, Any]:
        """Handle list resource type."""
        async with self.pool.get_connection() as wrapper:
            handler_instance = wrapper.connection
            # Get all records with basic fields
            records = handler_instance.execute_kw(
                model_name, "search_read", [[], ["id", "name"]],
                {"limit": 100},  # Limit to prevent overwhelming
                uid=auth_details["uid"], password=auth_details["password"]
            )

        return {
            "contents": [
                {
                    "uri": f"odoo://{model_name}/list",
                    "mimeType": "application/json",
                    "text": json.dumps(records)
                }
            ]
        }

    async def _handle_binary_resource(self, model_name: str, field_name: str, id_str: str, auth_details: Dict[str, Any]) -> Dict[str, Any]:
        """Handle binary field resource type."""
        try:
            record_id = int(id_str)
        except ValueError:
            raise ProtocolError(f"Invalid record ID: {id_str}")

        async with self.pool.get_connection() as wrapper:
            handler_instance = wrapper.connection
            # Read only the binary field
            record_data = handler_instance.execute_kw(
                model_name, "read", [[record_id], [field_name]],
                {},
                uid=auth_details["uid"], password=auth_details["password"]
            )

        if not record_data:
            raise OdooMCPError(f"Resource not found: {model_name}/{id_str}")

        binary_data = record_data[0].get(field_name)
        if not binary_data:
            raise OdooMCPError(f"Binary field {field_name} not found or empty")

        # Decode base64 binary data
        try:
            import base64
            binary_content = base64.b64decode(binary_data)
        except Exception as e:
            raise OdooMCPError(f"Failed to decode binary data: {e}")

        return {
            "contents": [
                {
                    "uri": f"odoo://{model_name}/binary/{field_name}/{id_str}",
                    "mimeType": "application/octet-stream",
                    "blob": binary_content
                }
            ]
        }

    async def _handle_record_resource(self, model_name: str, id_str: str, auth_details: Dict[str, Any]) -> Dict[str, Any]:
        """Handle single record resource type."""
        try:
            record_id = int(id_str)
        except ValueError:
            raise ProtocolError(f"Invalid record ID: {id_str}")

        # Try to get from cache first
        cache_key = f"{model_name}:{record_id}"
        if cache_manager and CACHE_TYPE == 'cachetools':
            cached_data = cache_manager.get(cache_key)
            if cached_data:
                return {
                    "contents": [
                        {
                            "uri": f"odoo://{model_name}/{id_str}",
                            "mimeType": "application/json",
                            "text": json.dumps(cached_data)
                        }
                    ]
                }

        async with self.pool.get_connection() as wrapper:
            handler_instance = wrapper.connection
            # Read all fields
            record_data = handler_instance.execute_kw(
                model_name, "read", [[record_id]],
                {},
                uid=auth_details["uid"], password=auth_details["password"]
            )

        if not record_data:
            raise OdooMCPError(f"Resource not found: {model_name}/{id_str}")

        # Cache the result
        if cache_manager and CACHE_TYPE == 'cachetools':
            cache_manager.set(cache_key, record_data[0])

        return {
            "contents": [
                {
                    "uri": f"odoo://{model_name}/{id_str}",
                    "mimeType": "application/json",
                    "text": json.dumps(record_data[0])
                }
            ]
        }

    async def _get_odoo_auth(self, session_manager: SessionManager, config: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Union[int, str]]:
        """Get Odoo authentication details."""
        session_id = params.get("session_id")
        uid = params.get("uid")
        password = params.get("password")

        if session_id:
            session = session_manager.get_session(session_id)
            if not session:
                raise AuthError(f"Invalid session: {session_id}")
            return {
                "uid": session.user_id,
                "password": config.get('api_key') or config.get('password')
            }
        elif uid is not None and password is not None:
            return {"uid": uid, "password": password}
        else:
            raise AuthError("Authentication required")

    async def _notify_resource_update(self, uri: str, data: Dict[str, Any]):
        """
        Notify SSE clients about resource updates.
        """
        if not self.protocol.sse_clients:
            logger.debug(f"No SSE clients connected, skipping notification for {uri}")
            return

        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/resources/updated",
            "params": {
                "uri": uri,
                "data": data,
                "timestamp": datetime.now().isoformat()
            }
        }

        try:
            await self.protocol.sse_response_queue.put(notification)
            logger.debug(f"Queued notification for {uri}")
        except asyncio.QueueFull:
            logger.warning(f"SSE queue full, dropping resource update notification for {uri}")

async def main(config_path: str = "odoo_mcp/config/config.dev.yaml"):
    """Main entry point."""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        logging.basicConfig(level=logging.ERROR)
        logger.critical(f"Configuration file not found: {config_path}")
        return
    except yaml.YAMLError as e:
        logging.basicConfig(level=logging.ERROR)
        logger.critical(f"Error parsing configuration file: {e}")
        return

    with contextlib.redirect_stdout(sys.stderr):
        setup_logging(config)

    if cache_manager and CACHE_TYPE == 'cachetools':
        try:
            cache_manager.configure(config)
        except Exception as e:
            logger.error(f"Failed to configure CacheManager: {e}")

    try:
        server = OdooMCPServer(config)
        await server.run()
    except Exception as e:
        logger.critical(f"Server error: {e}", exc_info=True)

def main_cli():
    """Command line entry point."""
    parser = argparse.ArgumentParser(description="Odoo MCP Server")
    parser.add_argument(
        "-c", "--config",
        default="odoo_mcp/config/config.dev.yaml",
        help="Path to configuration file"
    )
    args = parser.parse_args()

    try:
        asyncio.run(main(config_path=args.config))
    except KeyboardInterrupt:
        if not logger.hasHandlers():
            logging.basicConfig(level=logging.INFO)
        logger.info("Server stopped by user")
    finally:
        if not logger.hasHandlers():
            logging.basicConfig(level=logging.INFO)
        logger.info("Exiting")

if __name__ == "__main__":
    main_cli()
