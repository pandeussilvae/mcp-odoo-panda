import asyncio
import sys
import json
import logging
import signal
from typing import Dict, Any, Optional, Type, Union, List, Callable, Set
import yaml
from datetime import datetime
import argparse
import contextlib
from functools import wraps

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

# Import MCP types
from mcp.types import (
    Server, Resource, Tool, Prompt,
    ServerInfo, ClientInfo, ResourceTemplate,
    GetPromptResult, PromptMessage, TextContent
)

# Import SSE components
try:
    from aiohttp import web
    from aiohttp_sse import sse_response
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

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

        # SSE specific state
        self._sse_clients: Set[web.StreamResponse] = set()
        self._sse_response_queue = asyncio.Queue(maxsize=config.get('sse_queue_maxsize', 1000))
        self._allowed_origins = config.get('allowed_origins', ['*'])
        self._sse_task: Optional[asyncio.Task] = None

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

    @Server.list_resources()
    async def list_resources(self) -> List[Resource]:
        """List available resources."""
        return [
            Resource(
                uri="odoo://{model}/{id}",
                name="Odoo Record",
                description="Represents a single record in an Odoo model.",
                mimeType="application/json"
            ),
            Resource(
                uri="odoo://{model}/list",
                name="Odoo Record List",
                description="Represents a list of records in an Odoo model.",
                mimeType="application/json"
            ),
            Resource(
                uri="odoo://{model}/binary/{field}/{id}",
                name="Odoo Binary Field",
                description="Represents a binary field value from an Odoo record.",
                mimeType="application/octet-stream"
            )
        ]

    @Server.read_resource()
    async def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read a resource."""
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
            return await self._handle_list_resource(model_name, auth_details)
        elif parts[1] == "binary":
            # Binary field
            if len(parts) != 4:
                raise ProtocolError(f"Invalid binary field URI format: {uri}")
            model_name, _, field_name, id_str = parts
            return await self._handle_binary_resource(model_name, field_name, id_str, auth_details)
        else:
            # Single record
            if len(parts) != 2:
                raise ProtocolError(f"Invalid record URI format: {uri}")
            model_name, id_str = parts
            return await self._handle_record_resource(model_name, id_str, auth_details)

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

    @Server.list_tools()
    async def list_tools(self) -> List[Tool]:
        """List available tools."""
        return [
            Tool(
                name="odoo_search_read",
                description="Search and read Odoo records",
                inputSchema={
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
                inputSchema={
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
                inputSchema={
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
                inputSchema={
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
                inputSchema={
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
                inputSchema={
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

    @Server.call_tool()
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool."""
        # Rate limiting
        acquired = await self.rate_limiter.acquire()
        if not acquired:
            raise OdooMCPError("Rate limit exceeded")

        # Get authentication details
        auth_details = await self._get_odoo_auth(self.session_manager, self.config, arguments)

        # Call the appropriate tool
        if name == "odoo_search_read":
            return await self._handle_search_read(arguments, auth_details)
        elif name == "odoo_read":
            return await self._handle_read(arguments, auth_details)
        elif name == "odoo_create":
            return await self._handle_create(arguments, auth_details)
        elif name == "odoo_write":
            return await self._handle_write(arguments, auth_details)
        elif name == "odoo_unlink":
            return await self._handle_unlink(arguments, auth_details)
        elif name == "odoo_call_method":
            return await self._handle_call_method(arguments, auth_details)

        raise ProtocolError(f"Unknown tool: {name}")

    async def _handle_search_read(self, arguments: Dict[str, Any], auth_details: Dict[str, Any]) -> Dict[str, Any]:
        """Handle odoo_search_read tool."""
        model = arguments.get("model")
        domain = arguments.get("domain", [])
        fields = arguments.get("fields", [])
        limit = arguments.get("limit", 80)
        offset = arguments.get("offset", 0)
        context = arguments.get("context", {})

        async with self.pool.get_connection() as wrapper:
            handler_instance = wrapper.connection
            result = handler_instance.execute_kw(
                model, "search_read", [domain, fields],
                {"limit": limit, "offset": offset, "context": context},
                uid=auth_details["uid"], password=auth_details["password"]
            )

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result)
                }
            ]
        }

    async def _handle_read(self, arguments: Dict[str, Any], auth_details: Dict[str, Any]) -> Dict[str, Any]:
        """Handle odoo_read tool."""
        model = arguments.get("model")
        ids = arguments.get("ids")
        fields = arguments.get("fields", [])
        context = arguments.get("context", {})

        async with self.pool.get_connection() as wrapper:
            handler_instance = wrapper.connection
            result = handler_instance.execute_kw(
                model, "read", [ids, fields],
                {"context": context},
                uid=auth_details["uid"], password=auth_details["password"]
            )

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result)
                }
            ]
        }

    async def _handle_create(self, arguments: Dict[str, Any], auth_details: Dict[str, Any]) -> Dict[str, Any]:
        """Handle odoo_create tool."""
        model = arguments.get("model")
        values = arguments.get("values")
        context = arguments.get("context", {})

        async with self.pool.get_connection() as wrapper:
            handler_instance = wrapper.connection
            result = handler_instance.execute_kw(
                model, "create", [values],
                {"context": context},
                uid=auth_details["uid"], password=auth_details["password"]
            )

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result)
                }
            ]
        }

    async def _handle_write(self, arguments: Dict[str, Any], auth_details: Dict[str, Any]) -> Dict[str, Any]:
        """Handle odoo_write tool."""
        model = arguments.get("model")
        ids = arguments.get("ids")
        values = arguments.get("values")
        context = arguments.get("context", {})

        async with self.pool.get_connection() as wrapper:
            handler_instance = wrapper.connection
            result = handler_instance.execute_kw(
                model, "write", [ids, values],
                {"context": context},
                uid=auth_details["uid"], password=auth_details["password"]
            )

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result)
                }
            ]
        }

    async def _handle_unlink(self, arguments: Dict[str, Any], auth_details: Dict[str, Any]) -> Dict[str, Any]:
        """Handle odoo_unlink tool."""
        model = arguments.get("model")
        ids = arguments.get("ids")
        context = arguments.get("context", {})

        async with self.pool.get_connection() as wrapper:
            handler_instance = wrapper.connection
            result = handler_instance.execute_kw(
                model, "unlink", [ids],
                {"context": context},
                uid=auth_details["uid"], password=auth_details["password"]
            )

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result)
                }
            ]
        }

    async def _handle_call_method(self, arguments: Dict[str, Any], auth_details: Dict[str, Any]) -> Dict[str, Any]:
        """Handle odoo_call_method tool."""
        model = arguments.get("model")
        method = arguments.get("method")
        ids = arguments.get("ids")
        args = arguments.get("args", [])
        kwargs = arguments.get("kwargs", {})
        context = arguments.get("context", {})

        # Construct arguments for execute_kw
        execute_args = [ids] + args if ids else args
        execute_kwargs = {**kwargs, "context": context}

        async with self.pool.get_connection() as wrapper:
            handler_instance = wrapper.connection
            result = handler_instance.execute_kw(
                model, method, execute_args, execute_kwargs,
                uid=auth_details["uid"], password=auth_details["password"]
            )

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result)
                }
            ]
        }

    @Server.list_prompts()
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

    @Server.get_prompt()
    async def get_prompt(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> GetPromptResult:
        """Get a prompt."""
        if name == "analyze-record":
            uri = arguments.get("uri") if arguments else None
            if not uri:
                raise ProtocolError("Missing required argument: uri")

            # Parse URI to get model and ID
            parts = uri[len("odoo://"):].split('/')
            if len(parts) != 2:
                raise ProtocolError(f"Invalid URI format: {uri}")
            model_name, id_str = parts

            return GetPromptResult(
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(
                            type="text",
                            text=f"Please analyze this Odoo record:\n\n"
                                 f"Model: {model_name}\n"
                                 f"ID: {id_str}\n\n"
                                 f"Provide insights about:\n"
                                 f"1. Record structure and fields\n"
                                 f"2. Related records and dependencies\n"
                                 f"3. Business rules and constraints\n"
                                 f"4. Potential issues or improvements"
                        )
                    )
                ]
            )

        elif name == "create-record":
            model = arguments.get("model") if arguments else None
            template = arguments.get("template") if arguments else None
            if not model:
                raise ProtocolError("Missing required argument: model")

            return GetPromptResult(
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(
                            type="text",
                            text=f"Let's create a new record in {model}.\n\n"
                                 f"Please guide me through the required fields and optional fields.\n"
                                 f"{'Using template: ' + template if template else ''}\n\n"
                                 f"Consider:\n"
                                 f"1. Required fields and their types\n"
                                 f"2. Default values and constraints\n"
                                 f"3. Related fields and dependencies\n"
                                 f"4. Business rules and validations"
                        )
                    )
                ]
            )

        elif name == "update-record":
            uri = arguments.get("uri") if arguments else None
            if not uri:
                raise ProtocolError("Missing required argument: uri")

            # Parse URI to get model and ID
            parts = uri[len("odoo://"):].split('/')
            if len(parts) != 2:
                raise ProtocolError(f"Invalid URI format: {uri}")
            model_name, id_str = parts

            return GetPromptResult(
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(
                            type="text",
                            text=f"Let's update this Odoo record:\n\n"
                                 f"Model: {model_name}\n"
                                 f"ID: {id_str}\n\n"
                                 f"Please guide me through:\n"
                                 f"1. Current field values\n"
                                 f"2. Editable fields and their types\n"
                                 f"3. Dependencies and constraints\n"
                                 f"4. Impact of changes on related records"
                        )
                    )
                ]
            )

        elif name == "advanced-search":
            model = arguments.get("model") if arguments else None
            fields = arguments.get("fields") if arguments else None
            if not model:
                raise ProtocolError("Missing required argument: model")

            return GetPromptResult(
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(
                            type="text",
                            text=f"Let's build an advanced search for {model}.\n\n"
                                 f"Please help me construct a search domain considering:\n"
                                 f"1. Available fields and their types\n"
                                 f"2. Search operators and conditions\n"
                                 f"3. Related fields and joins\n"
                                 f"4. Performance considerations\n\n"
                                 f"{'Fields to return: ' + ', '.join(fields) if fields else ''}"
                        )
                    )
                ]
            )

        elif name == "call-method":
            uri = arguments.get("uri") if arguments else None
            method = arguments.get("method") if arguments else None
            if not uri or not method:
                raise ProtocolError("Missing required arguments: uri and method")

            # Check if URI is a model name or record URI
            if uri.startswith("odoo://"):
                parts = uri[len("odoo://"):].split('/')
                if len(parts) != 2:
                    raise ProtocolError(f"Invalid URI format: {uri}")
                model_name, id_str = parts
                is_model_method = False
            else:
                model_name = uri
                is_model_method = True

            return GetPromptResult(
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(
                            type="text",
                            text=f"Let's call the {method} method on {'model' if is_model_method else 'record'} {model_name}.\n\n"
                                 f"Please guide me through:\n"
                                 f"1. Required parameters and their types\n"
                                 f"2. Optional parameters and defaults\n"
                                 f"3. Return value format\n"
                                 f"4. Potential side effects\n"
                                 f"5. Error handling"
                        )
                    )
                ]
            )

        raise ProtocolError(f"Unknown prompt: {name}")

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

    @Server.subscribe_resource()
    async def subscribe_resource(self, uri: str) -> None:
        """Subscribe to resource updates."""
        # Parse URI
        if not uri.startswith("odoo://"):
            raise ProtocolError(f"Invalid URI scheme: {uri}")
        
        parts = uri[len("odoo://"):].split('/')
        if len(parts) < 2:
            raise ProtocolError(f"Invalid URI format: {uri}")

        # For now, we only support subscribing to record updates
        if len(parts) != 2 or parts[1] == "list" or parts[1] == "binary":
            raise ProtocolError("Only single record subscriptions are supported")

        model_name, id_str = parts
        try:
            record_id = int(id_str)
        except ValueError:
            raise ProtocolError(f"Invalid record ID: {id_str}")

        # Subscribe to Odoo bus channel
        channel = f"odoo://{model_name}/{id_str}"
        await self.bus_handler.subscribe(channel)
        logger.info(f"Subscribed to updates for {uri}")

    @Server.unsubscribe_resource()
    async def unsubscribe_resource(self, uri: str) -> None:
        """Unsubscribe from resource updates."""
        # Parse URI
        if not uri.startswith("odoo://"):
            raise ProtocolError(f"Invalid URI scheme: {uri}")
        
        parts = uri[len("odoo://"):].split('/')
        if len(parts) < 2:
            raise ProtocolError(f"Invalid URI format: {uri}")

        # For now, we only support unsubscribing from record updates
        if len(parts) != 2 or parts[1] == "list" or parts[1] == "binary":
            raise ProtocolError("Only single record unsubscriptions are supported")

        model_name, id_str = parts
        try:
            record_id = int(id_str)
        except ValueError:
            raise ProtocolError(f"Invalid record ID: {id_str}")

        # Unsubscribe from Odoo bus channel
        channel = f"odoo://{model_name}/{id_str}"
        await self.bus_handler.unsubscribe(channel)
        logger.info(f"Unsubscribed from updates for {uri}")

    async def _sse_handler(self, request: web.Request) -> web.StreamResponse:
        """
        Handle SSE client connections.
        """
        logger.info(f"SSE client connection attempt from: {request.remote}")
        resp: Optional[web.StreamResponse] = None
        request_origin = request.headers.get('Origin')
        allowed = False
        cors_headers = {}

        # CORS check
        if '*' in self._allowed_origins:
            allowed = True
            cors_headers['Access-Control-Allow-Origin'] = '*'
        elif request_origin and request_origin in self._allowed_origins:
            allowed = True
            cors_headers['Access-Control-Allow-Origin'] = request_origin
            cors_headers['Access-Control-Allow-Credentials'] = 'true'
        else:
            logger.warning(f"SSE connection denied for origin: {request_origin}")
            return web.Response(status=403, text="Origin not allowed")

        if allowed:
            cors_headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            cors_headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'

        try:
            resp = await sse_response(request, headers=cors_headers)
            self._sse_clients.add(resp)
            await resp.prepare(request)
            logger.info(f"SSE client connected: {request.remote}")

            # Send initial connection message
            try:
                initial_message = {
                    "jsonrpc": "2.0",
                    "method": "notifications/connection/established",
                    "params": {
                        "client_id": id(resp),
                        "timestamp": datetime.now().isoformat()
                    }
                }
                await resp.send(json.dumps(initial_message))
                logger.debug(f"Sent initial connection message to client {request.remote}")
            except Exception as e:
                logger.error(f"Failed to send initial connection message to {request.remote}: {e}")

            while not resp.task.done():
                try:
                    response_data = await self._sse_response_queue.get()
                    response_str = json.dumps(response_data)
                    masked_response_str = mask_sensitive_data(response_str, self.config)
                    logger.debug(f"Sending SSE event (masked): {masked_response_str}")
                    await resp.send(response_str)
                    self._sse_response_queue.task_done()
                except asyncio.CancelledError:
                    logger.info(f"SSE handler task cancelled for {request.remote}")
                    break
                except Exception as e:
                    logger.exception(f"Error sending SSE event to {request.remote}: {e}")
                    break

        except Exception as e:
            logger.exception(f"Error in SSE handler for {request.remote}: {e}")
        finally:
            if resp and resp in self._sse_clients:
                self._sse_clients.remove(resp)
                logger.info(f"SSE client disconnected: {request.remote}")

        return resp if resp else web.Response(status=500, text="Failed to establish SSE connection")

    async def _post_handler(self, request: web.Request) -> web.Response:
        """
        Handle POST requests in SSE mode.
        """
        try:
            request_data = await request.json()
            masked_request_str = mask_sensitive_data(json.dumps(request_data), self.config)
            logger.info(f"Received POST request (masked): {masked_request_str}")

            # Validate request format
            if not isinstance(request_data, dict):
                raise ProtocolError("Invalid request format: expected JSON object")

            # Handle request and put response on SSE queue
            try:
                response_data = await self.handle_request(request_data)
                try:
                    self._sse_response_queue.put_nowait(response_data)
                    return web.Response(status=202, text="Request accepted")
                except asyncio.QueueFull:
                    logger.error(f"SSE response queue is full")
                    return web.json_response(
                        {
                            "jsonrpc": "2.0",
                            "id": request_data.get("id"),
                            "error": {
                                "code": -32001,
                                "message": "Server busy, SSE queue full"
                            }
                        },
                        status=503
                    )
            except OdooMCPError as e:
                logger.error(f"Odoo MCP error handling request: {e}")
                return web.json_response(
                    {
                        "jsonrpc": "2.0",
                        "id": request_data.get("id"),
                        "error": {
                            "code": -32000,
                            "message": str(e)
                        }
                    },
                    status=400
                )
            except Exception as e:
                logger.exception(f"Unexpected error handling request: {e}")
                return web.json_response(
                    {
                        "jsonrpc": "2.0",
                        "id": request_data.get("id"),
                        "error": {
                            "code": -32603,
                            "message": "Internal server error"
                        }
                    },
                    status=500
                )

        except json.JSONDecodeError:
            logger.warning("Failed to decode JSON POST request")
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error"
                    }
                },
                status=400
            )
        except Exception as e:
            logger.exception(f"Error handling POST request: {e}")
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": "Internal server error"
                    }
                },
                status=500
            )

    async def _run_sse_server(self):
        """
        Run the server in SSE mode.
        """
        if not AIOHTTP_AVAILABLE:
            logger.critical("aiohttp and/or aiohttp-sse not installed")
            logger.critical("Install with: pip install aiohttp aiohttp-sse")
            return

        app = web.Application()
        app.router.add_get('/events', self._sse_handler)
        app.router.add_post('/mcp', self._post_handler)

        # Add middleware for request logging
        @web.middleware
        async def log_middleware(request, handler):
            start_time = datetime.now()
            try:
                response = await handler(request)
                duration = (datetime.now() - start_time).total_seconds()
                logger.info(f"{request.method} {request.path} - {response.status} ({duration:.3f}s)")
                return response
            except Exception as e:
                duration = (datetime.now() - start_time).total_seconds()
                logger.exception(f"{request.method} {request.path} - Error ({duration:.3f}s): {e}")
                raise

        app.middlewares.append(log_middleware)

        host = self.config.get('host', 'localhost')
        port = self.config.get('port', 8080)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        logger.info(f"Starting SSE server on http://{host}:{port}")
        await site.start()

        # Keep server running until shutdown
        while not self._shutdown_requested:
            await asyncio.sleep(1)

        # Cleanup
        logger.info("Shutting down SSE server...")
        await runner.cleanup()
        logger.info("SSE server stopped")

    async def _notify_resource_update(self, uri: str, data: Dict[str, Any]):
        """
        Notify SSE clients about resource updates.
        """
        if not self._sse_clients:
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
            self._sse_response_queue.put_nowait(notification)
            logger.debug(f"Queued notification for {uri}")
        except asyncio.QueueFull:
            logger.warning(f"SSE queue full, dropping resource update notification for {uri}")

    async def run(self):
        """
        Start the server and run the appropriate communication loop.
        """
        self._shutdown_requested = False
        loop = asyncio.get_running_loop()

        # Add signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.request_shutdown, sig)

        logger.info("Starting Odoo MCP Server...")
        await self.pool.start_health_checks()
        await self.session_manager.start_cleanup_task()
        await self.bus_handler.start()

        try:
            if self.connection_type == 'stdio':
                await self._run_stdio_server()
            elif self.connection_type == 'sse':
                await self._run_sse_server()
            else:
                raise ConfigurationError(f"Unsupported connection_type: {self.connection_type}")
        finally:
            logger.info("Server run loop finished. Initiating cleanup...")
            await self.shutdown()

    def request_shutdown(self, sig: Optional[signal.Signals] = None):
        """
        Signal handler to initiate graceful shutdown.
        """
        if not self._shutdown_requested:
            signame = sig.name if sig else "signal"
            logger.info(f"Received {signame}, requesting shutdown...")
            self._shutdown_requested = True
        else:
            logger.warning("Shutdown already requested")

    async def shutdown(self):
        """
        Perform graceful shutdown of server components.
        """
        logger.info("Starting graceful shutdown...")
        await self.session_manager.stop_cleanup_task()
        await self.pool.close()
        await self.bus_handler.stop()

        # Close SSE connections
        if self._sse_clients:
            for client in self._sse_clients:
                await client.close()
            self._sse_clients.clear()

        logger.info("MCP Server shutdown complete")

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
