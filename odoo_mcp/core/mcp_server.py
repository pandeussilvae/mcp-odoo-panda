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
import sys
import json
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
import aiohttp
import aiohttp.web as web
import base64

# Import core components
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler
from odoo_mcp.core.jsonrpc_handler import JSONRPCHandler
from odoo_mcp.core.connection_pool import ConnectionPool
from odoo_mcp.core.authenticator import Authenticator
from odoo_mcp.core.session_manager import SessionManager
from odoo_mcp.security.utils import RateLimiter, mask_sensitive_data
from odoo_mcp.error_handling.exceptions import (
    OdooMCPError, AuthError, NetworkError, ProtocolError,
    ConfigurationError, ConnectionError, SessionError,
    OdooValidationError, OdooRecordNotFoundError, PoolTimeoutError,
    RateLimitError, ResourceError, ToolError, PromptError,
    CacheError, BusError
)
from odoo_mcp.core.logging_config import setup_logging, setup_logging_from_config
from odoo_mcp.performance.caching import get_cache_manager, CACHE_TYPE, initialize_cache_manager
from odoo_mcp.core.bus_handler import OdooBusHandler
from odoo_mcp.core.protocol_handler import ProtocolHandler
from odoo_mcp.core.capabilities_manager import CapabilitiesManager, ResourceTemplate, Tool, Prompt, ResourceType
from odoo_mcp.core.resource_manager import ResourceManager, Resource

# Constants
SERVER_NAME = "odoo-mcp-server"
SERVER_VERSION = "2024.2.5"  # Using CalVer: YYYY.MM.DD
PROTOCOL_VERSION = "2025-03-26"  # Current protocol version
LEGACY_PROTOCOL_VERSIONS = ["2024-11-05"]  # Supported legacy versions

logger = logging.getLogger(__name__)

@dataclass
class ServerInfo:
    """Information about the MCP server."""
    name: str
    version: str
    capabilities: Dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict):
        allowed = {"name", "version", "capabilities"}
        filtered = {k: v for k, v in data.items() if k in allowed}
        return cls(**filtered)

@dataclass
class ClientInfo:
    """Information about the MCP client."""
    name: Optional[str] = None
    version: Optional[str] = None
    capabilities: Dict[str, Any] = field(default_factory=dict)
    protocol_version: str = PROTOCOL_VERSION

    @classmethod
    def from_dict(cls, data: dict):
        allowed = {"name", "version", "capabilities", "protocol_version"}
        filtered = {k: v for k, v in data.items() if k in allowed}
        return cls(**filtered)

    def is_compatible(self) -> bool:
        """Check if the client's protocol version is compatible."""
        return self.protocol_version == PROTOCOL_VERSION or self.protocol_version in LEGACY_PROTOCOL_VERSIONS

@dataclass
class JsonRpcRequest:
    """JSON-RPC request object."""
    id: Optional[Union[str, int]]
    method: str
    params: Dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            id=data.get('id'),
            method=data.get('method', ''),
            params=data.get('params', {})
        )

class Server(ABC):
    """Base class for MCP servers."""
    
    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version

    @abstractmethod
    async def initialize(self, client_info: ClientInfo) -> ServerInfo:
        """Initialize the server with client information."""
        pass

    @abstractmethod
    async def get_resource(self, uri: str) -> Resource:
        """Get a resource by URI."""
        pass

    @abstractmethod
    async def list_resources(self, template: Optional[ResourceTemplate] = None) -> List[Resource]:
        """List available resources."""
        pass

    @abstractmethod
    async def list_tools(self) -> List[Tool]:
        """List available tools."""
        pass

    @abstractmethod
    async def list_prompts(self) -> List[Prompt]:
        """List available prompts."""
        pass

    @abstractmethod
    async def get_prompt(self, name: str, args: Dict[str, Any]) -> Any:
        """Get a prompt by name."""
        pass

    @abstractmethod
    async def run(self):
        """Run the server."""
        pass

    @abstractmethod
    async def stop(self):
        """Stop the server."""
        pass

class StdioProtocol:
    """Stdio-based communication protocol."""
    
    def __init__(self, request_handler: Callable):
        self.request_handler = request_handler
        self.running = False

    async def run(self):
        """Run the protocol."""
        self.running = True
        while self.running:
            try:
                # Use asyncio.get_event_loop().run_in_executor to read from stdin
                line = await asyncio.get_event_loop().run_in_executor(None, input)
                if not line:
                    continue
                
                request = json.loads(line)
                response = self.request_handler(request)
                print(json.dumps(response))
                sys.stdout.flush()
            except EOFError:
                logger.info("Received EOF, shutting down")
                self.running = False
                break
            except json.JSONDecodeError:
                logger.error("Invalid JSON received")
            except Exception as e:
                logger.error(f"Error processing request: {e}")
                if not self.running:
                    break

    def stop(self):
        """Stop the protocol."""
        self.running = False

class StreamableHTTPProtocol:
    """HTTP-based communication protocol with streaming support."""
    
    def __init__(self, request_handler: Callable, config: Dict[str, Any]):
        self.request_handler = request_handler
        self.config = config
        self.running = False
        self.app = web.Application()
        
        # Configura CORS
        self.app.router.add_post('/mcp', self._handle_request)
        self.app.router.add_get('/sse', self._handle_sse)
        self.app.router.add_options('/mcp', self._handle_options)
        self.app.router.add_options('/sse', self._handle_options)
        
        # Aggiungi middleware per CORS
        @web.middleware
        async def cors_middleware(request, handler):
            response = await handler(request)
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            return response
        
        self.app.middlewares.append(cors_middleware)
        
        self.runner = None
        self.site = None

    async def _handle_request(self, request: web.Request) -> web.Response:
        """Handle HTTP request."""
        try:
            # Leggi il corpo della richiesta come bytes
            body = await request.read()
            
            # Prova a decodificare con UTF-8, se fallisce prova con latin-1
            try:
                data = json.loads(body.decode('utf-8'))
            except UnicodeDecodeError:
                data = json.loads(body.decode('latin-1'))
            
            response = self.request_handler(data)
            
            # Assicurati che la risposta sia codificata correttamente
            return web.json_response(
                response,
                content_type='application/json; charset=utf-8'
            )
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in request: {e}")
            return web.json_response({
                'jsonrpc': '2.0',
                'error': {
                    'code': -32700,
                    'message': 'Parse error: Invalid JSON'
                },
                'id': None
            }, status=400)
        except Exception as e:
            logger.error(f"Error handling request: {e}")
            return web.json_response({
                'jsonrpc': '2.0',
                'error': {
                    'code': -32603,
                    'message': str(e)
                },
                'id': None
            }, status=500)

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        """Handle Server-Sent Events request."""
        response = web.StreamResponse()
        response.headers['Content-Type'] = 'text/event-stream'
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['Connection'] = 'keep-alive'
        await response.prepare(request)

        try:
            while self.running:
                # Send a heartbeat every 30 seconds
                await response.write(b'event: heartbeat\ndata: {}\n\n')
                await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Error in SSE handler: {e}")
        finally:
            await response.write_eof()
        return response

    async def _handle_options(self, request: web.Request) -> web.Response:
        """Handle OPTIONS request for CORS preflight."""
        response = web.Response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

    async def run(self):
        """Run the protocol."""
        self.running = True
        try:
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            host = self.config.get('http', {}).get('host', '0.0.0.0')
            port = self.config.get('http', {}).get('port', 8080)
            self.site = web.TCPSite(self.runner, host, port)
            await self.site.start()
            logger.info(f"HTTP server started on {host}:{port}")
            
            # Keep the server running
            while self.running:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Error running HTTP server: {e}")
            self.running = False

    def stop(self):
        """Stop the protocol."""
        self.running = False
        if self.runner:
            asyncio.create_task(self.runner.cleanup())

class OdooMCPServer(Server):
    """
    Odoo MCP Server implementation.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the Odoo MCP Server.

        Args:
            config: The server configuration
        """
        super().__init__(SERVER_NAME, SERVER_VERSION)
        logger.info(f"Initializing OdooMCPServer with config: {config}")
        self.config = config.copy()  # Make a copy of the config to avoid modifying the original
        self.protocol_type = config.get('protocol', 'xmlrpc').lower()
        self.connection_type = config.get('connection_type', 'stdio').lower()
        self.running = False
        
        # Initialize core components
        self.protocol_handler = ProtocolHandler(PROTOCOL_VERSION)
        self.capabilities_manager = CapabilitiesManager(config)
        self.resource_manager = ResourceManager(
            cache_ttl=config.get('cache_ttl', 300)
        )

        # Initialize Odoo components
        logger.info(f"Initializing connection pool with protocol type: {self.protocol_type}")
        self.pool = ConnectionPool(self.config, self._get_handler_class())
        self.authenticator = Authenticator(self.config, self.pool)
        self.session_manager = SessionManager(self.config, self.authenticator, self.pool)
        self.rate_limiter = RateLimiter(
            requests_per_minute=config.get('requests_per_minute', 60),
            max_wait_seconds=config.get('rate_limit_max_wait_seconds', 30)
        )
        self.bus_handler = OdooBusHandler(self.config, self.pool)

        # Initialize protocol
        if self.connection_type == 'stdio':
            self.protocol = StdioProtocol(self._handle_request)
        elif self.connection_type in ['streamable_http', 'sse']:
            # Both streamable_http and sse use the same protocol implementation
            self.protocol = StreamableHTTPProtocol(self._handle_request, self.config)
        else:
            raise ConfigurationError(f"Unsupported connection type: {self.connection_type}")

        # Register resource handlers
        self._register_resource_handlers()

        # Register tools and prompts
        self._register_tools_and_prompts()

    def _get_handler_class(self) -> Type[Union[XMLRPCHandler, JSONRPCHandler]]:
        """Get the appropriate handler class based on protocol type."""
        if self.protocol_type == 'xmlrpc':
            return XMLRPCHandler
        elif self.protocol_type == 'jsonrpc':
            return JSONRPCHandler
        else:
            raise ConfigurationError(f"Unsupported protocol type: {self.protocol_type}")

    def _register_resource_handlers(self) -> None:
        """Register resource handlers."""
        logger.info("Registering resource handlers...")
        
        # Register Odoo record handler
        logger.info("Registering Odoo record handler...")
        self.resource_manager.register_resource_handler(
            "odoo://{model}/{id}",
            self._handle_odoo_record
        )
        logger.info("Odoo record handler registered successfully")

        # Register Odoo record list handler
        logger.info("Registering Odoo record list handler...")
        self.resource_manager.register_resource_handler(
            "odoo://{model}/list",
            self._handle_odoo_record_list
        )
        logger.info("Odoo record list handler registered successfully")

        # Register Odoo binary field handler
        logger.info("Registering Odoo binary field handler...")
        self.resource_manager.register_resource_handler(
            "odoo://{model}/binary/{field}/{id}",
            self._handle_odoo_binary_field
        )
        logger.info("Odoo binary field handler registered successfully")

        # Register specific model handlers
        logger.info("Registering specific model handlers...")
        models = ["res.partner", "res.users", "product.product", "sale.order", "ir.attachment"]
        for model in models:
            # Register record handler
            pattern = f"odoo://{model}/{{id}}"
            logger.info(f"Registering handler for pattern: {pattern}")
            self.resource_manager.register_resource_handler(
                pattern,
                lambda uri, model=model: self._handle_odoo_record(uri, model=model)
            )
            # Register list handler
            pattern = f"odoo://{model}/list"
            logger.info(f"Registering handler for pattern: {pattern}")
            self.resource_manager.register_resource_handler(
                pattern,
                lambda uri, model=model: self._handle_odoo_record_list(uri, model=model)
            )
            # Register binary handler if applicable
            if model == "ir.attachment":
                pattern = f"odoo://{model}/binary/{{field}}/{{id}}"
                logger.info(f"Registering handler for pattern: {pattern}")
                self.resource_manager.register_resource_handler(
                    pattern,
                    lambda uri, model=model: self._handle_odoo_binary_field(uri, model=model)
                )
        logger.info("Specific model handlers registered successfully")

        # Log all registered handlers
        logger.info("Registered handlers:")
        for pattern, handler in self.resource_manager._resource_handlers.items():
            logger.info(f"Pattern: {pattern}, Handler: {handler.__name__ if hasattr(handler, '__name__') else handler}")

    def _register_tools_and_prompts(self) -> None:
        """Register tools and prompts."""
        logger.info("Registering tools and prompts...")
        
        # Register resource templates
        logger.info("Registering resource templates...")
        templates = [
            ResourceTemplate(
                name="Odoo Record",
                type=ResourceType.RECORD,
                description="Represents a single record in an Odoo model",
                operations=["read", "write", "delete"],
                parameters={
                    "uri_template": "odoo://{model}/{id}",
                    "list_uri_template": "odoo://{model}/list",
                    "binary_uri_template": "odoo://{model}/binary/{field}/{id}"
                }
            ),
            ResourceTemplate(
                name="Odoo Record List",
                type=ResourceType.LIST,
                description="Represents a list of records in an Odoo model",
                operations=["read", "search"],
                parameters={
                    "uri_template": "odoo://{model}/list"
                }
            ),
            ResourceTemplate(
                name="Odoo Binary Field",
                type=ResourceType.BINARY,
                description="Represents a binary field value from an Odoo record",
                operations=["read", "write"],
                parameters={
                    "uri_template": "odoo://{model}/binary/{field}/{id}"
                }
            )
        ]

        for template in templates:
            logger.info(f"Registering resource template: {template.name}")
            self.capabilities_manager.register_resource(template)
            logger.info(f"Resource template {template.name} registered successfully")

        # Register prompts
        logger.info("Registering prompts...")
        prompts = [
            Prompt(
                name="analyze-record",
                description="Analyze an Odoo record",
                template="Analyze the record {model}/{id}",
                parameters={
                    "model": {"type": "string", "description": "Model name"},
                    "id": {"type": "integer", "description": "Record ID"}
                }
            ),
            Prompt(
                name="create-record",
                description="Create a new Odoo record",
                template="Create a new record in {model}",
                parameters={
                    "model": {"type": "string", "description": "Model name"},
                    "values": {"type": "object", "description": "Record values"}
                }
            ),
            Prompt(
                name="update-record",
                description="Update an Odoo record",
                template="Update record {model}/{id}",
                parameters={
                    "model": {"type": "string", "description": "Model name"},
                    "id": {"type": "integer", "description": "Record ID"},
                    "values": {"type": "object", "description": "Record values"}
                }
            )
        ]

        for prompt in prompts:
            logger.info(f"Registering prompt: {prompt.name}")
            self.capabilities_manager.register_prompt(prompt)
            logger.info(f"Prompt {prompt.name} registered successfully")

    async def _handle_odoo_record(self, uri: str, model: Optional[str] = None) -> Resource:
        """Handle Odoo record resource requests."""
        logger.info(f"Handling Odoo record request for URI: {uri}")
        try:
            # Parse URI
            parts = uri.replace("odoo://", "").split("/")
            if len(parts) != 2:
                logger.error(f"Invalid record URI format: {uri}")
                raise ProtocolError(f"Invalid record URI format: {uri}")
            
            model = model or parts[0]
            
            # Check if this is a list request
            if parts[1] == "list":
                logger.info(f"Handling list request for model {model}")
                # Get records from Odoo
                records = await self.pool.execute_kw(
                    model=model,
                    method="search_read",
                    args=[[], ["id", "name"]],
                    kwargs={"limit": 100, "offset": 0}
                )

                logger.info(f"Successfully retrieved {len(records)} records from model {model}")
                return Resource(
                    uri=uri,
                    type="list",
                    content=records,
                    mime_type="application/json",
                    metadata={
                        "model": model,
                        "count": len(records),
                        "last_modified": datetime.now().isoformat()
                    }
                )
            
            # Handle single record request
            try:
                record_id = int(parts[1])
            except ValueError:
                logger.error(f"Invalid record ID in URI: {uri}")
                raise ProtocolError(f"Invalid record ID in URI: {uri}")

            logger.info(f"Fetching record {record_id} from model {model}")
            # Get record from Odoo
            record = await self.pool.execute_kw(
                model=model,
                method="read",
                args=[[record_id]],
                kwargs={}
            )

            if not record:
                logger.error(f"Record {record_id} not found in model {model}")
                raise OdooRecordNotFoundError(f"Record {record_id} not found in model {model}")

            logger.info(f"Successfully retrieved record {record_id} from model {model}")
            return Resource(
                uri=uri,
                type="record",
                content=record[0],
                mime_type="application/json",
                metadata={
                    "model": model,
                    "id": record_id,
                    "last_modified": datetime.now().isoformat()
                }
            )

        except Exception as e:
            if isinstance(e, ProtocolError):
                raise
            logger.error(f"Error handling Odoo record request: {str(e)}")
            raise ProtocolError(f"Error handling Odoo record request: {str(e)}")

    async def _handle_odoo_record_list(self, uri: str, model: Optional[str] = None, domain: Optional[List] = None, fields: Optional[List[str]] = None, limit: Optional[int] = None, offset: Optional[int] = None) -> Resource:
        """Handle Odoo record list resource requests."""
        logger.info(f"Handling Odoo record list request for URI: {uri}")
        try:
            # Parse URI
            parts = uri.replace("odoo://", "").split("/")
            if len(parts) != 2 or parts[1] != "list":
                logger.error(f"Invalid record list URI format: {uri}")
                raise ProtocolError(f"Invalid record list URI format: {uri}")
            
            model = model or parts[0]
            logger.info(f"Fetching records from model {model}")

            # Set default values
            domain = domain or []
            fields = fields or ["id", "name"]
            limit = limit or 100
            offset = offset or 0

            # Get records from Odoo
            records = await self.pool.execute_kw(
                model=model,
                method="search_read",
                args=[domain, fields],
                kwargs={"limit": limit, "offset": offset}
            )

            logger.info(f"Successfully retrieved {len(records)} records from model {model}")
            return Resource(
                uri=uri,
                type="list",
                content=records,
                mime_type="application/json",
                metadata={
                    "model": model,
                    "count": len(records),
                    "domain": domain,
                    "fields": fields,
                    "limit": limit,
                    "offset": offset,
                    "last_modified": datetime.now().isoformat()
                }
            )

        except Exception as e:
            if isinstance(e, ProtocolError):
                raise
            logger.error(f"Error handling Odoo record list request: {str(e)}")
            raise ProtocolError(f"Error handling Odoo record list request: {str(e)}")

    async def _handle_odoo_binary_field(self, uri: str, model: Optional[str] = None) -> Resource:
        """Handle Odoo binary field resource requests."""
        try:
            # Parse URI
            parts = uri.replace("odoo://", "").split("/")
            if len(parts) != 4 or parts[1] != "binary":
                raise ProtocolError(f"Invalid binary field URI format: {uri}")
            
            model = model or parts[0]
            field = parts[2]
            try:
                record_id = int(parts[3])
            except ValueError:
                raise ProtocolError(f"Invalid record ID in URI: {uri}")

            # Get binary field from Odoo
            record = await self.pool.execute_kw(
                model=model,
                method="read",
                args=[[record_id], [field]],
                kwargs={}
            )

            if not record or field not in record[0]:
                raise OdooRecordNotFoundError(f"Binary field {field} not found in record {record_id} of model {model}")

            binary_data = record[0][field]
            if not binary_data:
                raise ProtocolError(f"Binary field {field} is empty in record {record_id}")

            return Resource(
                uri=uri,
                type="binary",
                content=binary_data,
                mime_type="application/octet-stream",
                metadata={
                    "model": model,
                    "field": field,
                    "id": record_id,
                    "last_modified": datetime.now().isoformat()
                }
            )

        except Exception as e:
            if isinstance(e, ProtocolError):
                raise
            raise ProtocolError(f"Error handling Odoo binary field request: {str(e)}")

    async def _notify_resource_update(self, uri: str, resource: Resource) -> None:
        """Notify about resource updates."""
        try:
            # Notify through bus handler
            await self.bus_handler.notify_resource_update(uri, resource)
            
            # Update cache
            self.resource_manager._resource_cache[uri] = resource
            
            # Notify subscribers
            await self.resource_manager._notify_subscribers(uri, resource)
            
            logger.info(f"Resource update notification sent for {uri}")
        except Exception as e:
            logger.error(f"Error notifying resource update for {uri}: {e}")
            raise ProtocolError(f"Error notifying resource update: {str(e)}")

    @property
    def capabilities(self) -> Dict[str, Any]:
        """Get server capabilities."""
        return self.capabilities_manager.get_capabilities()

    async def initialize(self, client_info: ClientInfo) -> ServerInfo:
        """Initialize the server with client information."""
        # Get the client's requested protocol version
        client_version = client_info.protocol_version
        
        # Validate protocol version
        if client_version != PROTOCOL_VERSION and client_version not in LEGACY_PROTOCOL_VERSIONS:
            raise ProtocolError(
                f"Unsupported protocol version: {client_version}. "
                f"Supported versions: {PROTOCOL_VERSION} and {', '.join(LEGACY_PROTOCOL_VERSIONS)}"
            )

        # Create server info
        return ServerInfo(
            name=SERVER_NAME,
            version=SERVER_VERSION,
            capabilities=self.capabilities
        )

    async def get_resource(self, uri: str) -> Resource:
        """Get a resource by URI."""
        logger.info(f"Getting resource for URI: {uri}")
        logger.info(f"Available handlers: {list(self.resource_manager._resource_handlers.keys())}")
        return await self.resource_manager.get_resource(uri)

    async def list_resources(self, template: Optional[ResourceTemplate] = None) -> List[Resource]:
        """List available resources."""
        try:
            if template:
                # List resources for a specific template
                if template.uri_template == "odoo://{model}/{id}":
                    # Get all models
                    models = await self.pool.execute_kw(
                        model="ir.model",
                        method="search_read",
                        args=[[], ["model", "name"]],
                        kwargs={}
                    )
                    resources = []
                    for model in models:
                        # Get first record of each model
                        records = await self.pool.execute_kw(
                            model=model["model"],
                            method="search_read",
                            args=[[], ["id"]],
                            kwargs={"limit": 1}
                        )
                        if records:
                            uri = f"odoo://{model['model']}/{records[0]['id']}"
                            resources.append(Resource(
                                uri=uri,
                                type="record",
                                content=records[0],
                                mime_type="application/json",
                                metadata={
                                    "model": model["model"],
                                    "name": model["name"],
                                    "id": records[0]["id"]
                                }
                            ))
                    return resources

                elif template.uri_template == "odoo://{model}/list":
                    # Get all models
                    models = await self.pool.execute_kw(
                        model="ir.model",
                        method="search_read",
                        args=[[], ["model", "name"]],
                        kwargs={}
                    )
                    resources = []
                    for model in models:
                        uri = f"odoo://{model['model']}/list"
                        resources.append(Resource(
                            uri=uri,
                            type="list",
                            content=[],
                            mime_type="application/json",
                            metadata={
                                "model": model["model"],
                                "name": model["name"]
                            }
                        ))
                    return resources

                elif template.uri_template == "odoo://{model}/binary/{field}/{id}":
                    # Get all models with binary fields
                    models = await self.pool.execute_kw(
                        model="ir.model",
                        method="search_read",
                        args=[[], ["model", "name"]],
                        kwargs={}
                    )
                    resources = []
                    for model in models:
                        # Get binary fields
                        fields = await self.pool.execute_kw(
                            model=model["model"],
                            method="fields_get",
                            args=[],
                            kwargs={}
                        )
                        binary_fields = {
                            name: info for name, info in fields.items()
                            if info.get("type") == "binary"
                        }
                        if binary_fields:
                            # Get first record
                            records = await self.pool.execute_kw(
                                model=model["model"],
                                method="search_read",
                                args=[[], ["id"]],
                                kwargs={"limit": 1}
                            )
                            if records:
                                for field in binary_fields:
                                    uri = f"odoo://{model['model']}/binary/{field}/{records[0]['id']}"
                                    resources.append(Resource(
                                        uri=uri,
                                        type="binary",
                                        content=None,
                                        mime_type="application/octet-stream",
                                        metadata={
                                            "model": model["model"],
                                            "name": model["name"],
                                            "field": field,
                                            "id": records[0]["id"]
                                        }
                                    ))
                    return resources

                else:
                    raise ProtocolError(f"Unsupported resource template: {template.uri_template}")

            else:
                # List all resource templates
                templates = self.capabilities_manager.list_resource_templates()
                return [
                    Resource(
                        uri=template["uriTemplate"],
                        type=template["type"],
                        content=None,
                        mime_type="application/json",
                        metadata={
                            "name": template["name"],
                            "description": template["description"],
                            "operations": template["operations"],
                            "parameters": template["parameters"]
                        }
                    )
                    for template in templates
                ]

        except Exception as e:
            if isinstance(e, ProtocolError):
                raise
            raise ProtocolError(f"Error listing resources: {str(e)}")

    async def list_tools(self) -> List[Tool]:
        """List available tools."""
        return list(self.capabilities_manager.tools.values())

    async def list_prompts(self) -> List[Prompt]:
        """List available prompts."""
        return list(self.capabilities_manager.prompts.values())

    async def get_prompt(self, name: str, args: Dict[str, Any]) -> Any:
        """Get a prompt by name."""
        try:
            # Find the prompt in capabilities
            prompt = next(
                (p for p in self.capabilities_manager._prompts if p.name == name),
                None
            )
            if not prompt:
                raise ProtocolError(f"Prompt not found: {name}")

            # Validate arguments
            for param_name, param_info in prompt.parameters.items():
                if param_name not in args:
                    raise ProtocolError(f"Missing required parameter: {param_name}")
                # TODO: Add type validation if needed

            # Execute prompt based on name
            if name == "analyze-record":
                return await self._handle_analyze_record_prompt(args)
            elif name == "create-record":
                return await self._handle_create_record_prompt(args)
            elif name == "update-record":
                return await self._handle_update_record_prompt(args)
            elif name == "advanced-search":
                return await self._handle_advanced_search_prompt(args)
            elif name == "call-method":
                return await self._handle_call_method_prompt(args)
            else:
                raise ProtocolError(f"Unsupported prompt: {name}")

        except Exception as e:
            if isinstance(e, ProtocolError):
                raise
            raise ProtocolError(f"Error executing prompt {name}: {str(e)}")

    async def _handle_analyze_record_prompt(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle analyze-record prompt."""
        model = args["model"]
        record_id = args["id"]

        # Get record details
        record = await self.pool.execute_kw(
            model=model,
            method="read",
            args=[[record_id]],
            kwargs={}
        )
        if not record:
            raise OdooRecordNotFoundError(f"Record {record_id} not found in model {model}")

        # Get field information
        fields_info = await self.pool.execute_kw(
            model=model,
            method="fields_get",
            args=[],
            kwargs={}
            )

        return {
            "analysis": {
                "record": record[0],
                "fields_info": fields_info,
                "model": model,
                "id": record_id
            }
        }

    async def _handle_create_record_prompt(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle create-record prompt."""
        model = args["model"]
        values = args["values"]

        # Get field information
        fields_info = await self.pool.execute_kw(
            model=model,
            method="fields_get",
            args=[],
            kwargs={}
        )

        # Validate required fields
        required_fields = {
            name: info for name, info in fields_info.items()
            if info.get("required", False)
        }
        missing_fields = [
            name for name in required_fields
            if name not in values
        ]
        if missing_fields:
            raise ProtocolError(f"Missing required fields: {', '.join(missing_fields)}")

        return {
            "prompt": {
                "model": model,
                "values": values,
                "fields_info": fields_info,
                "required_fields": required_fields
            }
        }

    async def _handle_update_record_prompt(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle update-record prompt."""
        model = args["model"]
        record_id = args["id"]
        values = args["values"]

        # Get current record
        record = await self.pool.execute_kw(
            model=model,
            method="read",
            args=[[record_id]],
            kwargs={}
        )
        if not record:
            raise OdooRecordNotFoundError(f"Record {record_id} not found in model {model}")

        # Get field information
        fields_info = await self.pool.execute_kw(
            model=model,
            method="fields_get",
            args=[],
            kwargs={}
        )

        return {
            "prompt": {
                "model": model,
                "id": record_id,
                "current_values": record[0],
                "new_values": values,
                "fields_info": fields_info
            }
        }

    async def _handle_advanced_search_prompt(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle advanced-search prompt."""
        model = args["model"]
        domain = args.get("domain", [])

        # Get field information
        fields_info = await self.pool.execute_kw(
            model=model,
            method="fields_get",
            args=[],
            kwargs={}
        )

        return {
            "prompt": {
                "model": model,
                "domain": domain,
                "fields_info": fields_info
            }
        }

    async def _handle_call_method_prompt(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle call-method prompt."""
        model = args["model"]
        method = args["method"]
        method_args = args.get("args", [])
        method_kwargs = args.get("kwargs", {})

        # Get method information
        methods_info = await self.pool.execute_kw(
            model=model,
            method="fields_get",
            args=[],
            kwargs={"attributes": ["method"]}
        )

        return {
            "prompt": {
                "model": model,
                "method": method,
                "args": method_args,
                "kwargs": method_kwargs,
                "methods_info": methods_info
            }
        }

    async def _handle_list_prompts(self, request: JsonRpcRequest) -> Dict[str, Any]:
        """Handle list_prompts request."""
        try:
            prompts = await self.list_prompts()
            return {
                'jsonrpc': '2.0',
                'result': {
                    'prompts': [
                        {
                            'name': prompt.name,
                            'description': prompt.description,
                            'template': prompt.template,
                            'parameters': prompt.parameters,
                            'inputSchema': {
                                'type': 'object',
                                'properties': prompt.parameters,
                                'required': list(prompt.parameters.keys())
                            }
                        }
                        for prompt in prompts
                    ]
                },
                'id': request.id
            }
        except Exception as e:
            logger.error(f"Error handling list_prompts request: {e}")
            return {
                'jsonrpc': '2.0',
                'error': {
                    'code': -32603,
                    'message': f"Internal error: {str(e)}"
                },
                'id': request.id
            }

    async def _handle_list_resource_templates(self, request: JsonRpcRequest) -> Dict[str, Any]:
        """Handle list_resource_templates request."""
        try:
            templates = self.capabilities_manager.list_resource_templates()
            templates_list = []
            for template in templates:
                templates_list.append({
                    "name": template["name"],
                    "type": template["type"],
                    "description": template["description"],
                    "operations": template["operations"],
                    "parameters": template["parameters"],
                    "uriTemplate": template["uriTemplate"]
                })
            
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "result": {
                    "id": "templates",
                    "method": "listResourceTemplates",
                    "resourceTemplates": templates_list
                }
            }
        except Exception as e:
            logger.error(f"Error handling list_resource_templates request: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }

    async def _handle_get_resource(self, request: JsonRpcRequest) -> Dict[str, Any]:
        """Handle get_resource request."""
        try:
            # PATCH: accetta sia stringa che dict per 'uri'
            uri = request.params['uri']
            if isinstance(uri, dict) and 'uri' in uri:
                uri = uri['uri']
            resource = await self.get_resource(uri)
            # Check if this is a Langchain request
            is_langchain = request.params.get('format') == 'langchain'
            if is_langchain:
                # Format for Langchain
                if isinstance(resource.content, (dict, list)):
                    content = json.dumps(resource.content)
                elif isinstance(resource.content, bytes):
                    content = base64.b64encode(resource.content).decode()
                else:
                    content = str(resource.content)
                return {
                    "jsonrpc": "2.0",
                    "id": request.id,
                    "result": {
                        "type": "text",
                        "text": content
                    }
                }
            # Standard MCP format
            if isinstance(resource, Resource):
                if isinstance(resource.content, (dict, list)):
                    content = {
                        "text": json.dumps(resource.content),
                        "blob": None
                    }
                elif isinstance(resource.content, bytes):
                    content = {
                        "text": None,
                        "blob": base64.b64encode(resource.content).decode()
                    }
                else:
                    content = {
                        "text": str(resource.content),
                        "blob": None
                    }
                uri_parts = resource.uri.replace("odoo://", "").split("/")
                model_name = uri_parts[0] if uri_parts else "unknown"
                contents = [{
                    "uri": resource.uri,
                    "type": resource.type,
                    "content": resource.content,
                    "mimeType": resource.mime_type,
                    "name": model_name,
                    **content
                }]
            elif isinstance(resource, dict):
                if 'content' in resource:
                    if isinstance(resource['content'], (dict, list)):
                        content = {
                            "text": json.dumps(resource['content']),
                            "blob": None
                        }
                    elif isinstance(resource['content'], bytes):
                        content = {
                            "text": None,
                            "blob": base64.b64encode(resource['content']).decode()
                        }
                    else:
                        content = {
                            "text": str(resource['content']),
                            "blob": None
                        }
                    resource.update(content)
                contents = [resource]
            else:
                contents = []
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "result": {
                    "id": uri,
                    "method": "readResource",
                    "contents": contents
                }
            }
        except Exception as e:
            logger.error(f"Error handling get_resource request: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }

    async def run(self):
        """Run the server."""
        try:
            logger.info("Starting server...")
            if self.config.get('protocol') == 'stdio':
                logger.info("Starting server in stdio mode")
                await self._run_stdio()
            else:
                logger.info("Starting server in streamable_http mode")
                await self._run_http()
        except Exception as e:
            logger.error(f"Error running server: {e}")
            raise

    async def _run_http(self):
        """Run the server in HTTP mode."""
        try:
            host = self.config.get('host', '0.0.0.0')
            port = self.config.get('port', 8080)
            logger.info(f"HTTP server started on {host}:{port}")
            
            # Initialize the server first
            await self.initialize(ClientInfo())
            
            # Create the HTTP server
            server = await asyncio.start_server(
                self._handle_http_connection,
                host,
                port
            )
            
            async with server:
                await server.serve_forever()
        except Exception as e:
            logger.error(f"Error in HTTP server: {e}")
            raise

    async def _handle_http_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle an HTTP connection."""
        try:
            # Read the request line and headers
            try:
                request_line = await reader.readline()
                if not request_line:
                    logger.warning("Empty request received")
                    return
                
                # Try to decode request line with different encodings
                encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
                decoded_line = None
                for encoding in encodings:
                    try:
                        decoded_line = request_line.decode(encoding)
                        logger.debug(f"Successfully decoded request line with {encoding}: {decoded_line}")
                        break
                    except UnicodeDecodeError:
                        continue
                
                if not decoded_line:
                    logger.error("Could not decode request line with any supported encoding")
                    return
                
                # Validate HTTP request line format
                if not decoded_line.startswith(('GET', 'POST', 'PUT', 'DELETE', 'OPTIONS')):
                    logger.error(f"Invalid HTTP request line: {decoded_line}")
                    return
                
                # Read headers
                headers = {}
                while True:
                    try:
                        line = await reader.readline()
                        if not line or line == b'\r\n':
                            break
                        
                        # Try to decode header line
                        decoded_header = None
                        for encoding in encodings:
                            try:
                                decoded_header = line.decode(encoding)
                                break
                            except UnicodeDecodeError:
                                continue
                        
                        if not decoded_header:
                            logger.error("Could not decode header line")
                            continue
                        
                        if ':' in decoded_header:
                            key, value = decoded_header.split(':', 1)
                            headers[key.strip().lower()] = value.strip()
                    except Exception as e:
                        logger.error(f"Error reading header: {e}")
                        continue
                
                logger.debug(f"Request headers: {headers}")
                
                # Read content length if present
                content_length = int(headers.get('content-length', 0))
                logger.debug(f"Content length: {content_length}")
                
                if content_length > 0:
                    # Read the request body
                    try:
                        request_data = await reader.read(content_length)
                        logger.debug(f"Request body (raw): {request_data}")
                        # Try different encodings for request body
                        decoded_data = None
                        for encoding in encodings:
                            try:
                                decoded_data = request_data.decode(encoding)
                                logger.debug(f"Successfully decoded request body with {encoding}")
                                break
                            except UnicodeDecodeError:
                                continue
                        if decoded_data is None:
                            raise UnicodeDecodeError("Could not decode request data with any supported encoding")
                        # Parse the request
                        request = json.loads(decoded_data)
                        logger.debug(f"Parsed request: {request}")
                        # Process the request
                        response = await self.process_request(request)
                        logger.debug(f"Got response from process_request: {response}")
                        logger.debug(f"Response type: {type(response)}")
                        logger.debug(f"Response attributes: {dir(response)}")
                        try:
                            # FIX: Se la risposta è già un dict, restituiscila così com'è
                            if isinstance(response, dict):
                                response_data = json.dumps(response).encode('utf-8')
                            else:
                                response_dict = {
                                    'jsonrpc': getattr(response, 'jsonrpc', '2.0'),
                                    'id': getattr(response, 'id', None)
                                }
                                error = getattr(response, 'error', None)
                                if error is not None:
                                    response_dict['error'] = error
                                else:
                                    response_dict['result'] = getattr(response, 'result', None)
                                logger.debug(f"Converted response dict: {response_dict}")
                                response_data = json.dumps(response_dict).encode('utf-8')
                            writer.write(b'HTTP/1.1 200 OK\r\n')
                            writer.write(b'Content-Type: application/json; charset=utf-8\r\n')
                            writer.write(f'Content-Length: {len(response_data)}\r\n'.encode('utf-8'))
                            writer.write(b'\r\n')
                            writer.write(response_data)
                            await writer.drain()
                        except Exception as e:
                            logger.error(f"Error converting response to dict: {e}")
                            logger.exception("Full traceback for conversion error:")
                            error_response = {
                                "error": f"Error converting response: {str(e)}",
                                "status": "error"
                            }
                            response_data = json.dumps(error_response).encode('utf-8')
                            writer.write(b'HTTP/1.1 500 Internal Server Error\r\n')
                            writer.write(b'Content-Type: application/json; charset=utf-8\r\n')
                            writer.write(f'Content-Length: {len(response_data)}\r\n'.encode('utf-8'))
                            writer.write(b'\r\n')
                            writer.write(response_data)
                            await writer.drain()
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON in request: {e}")
                        error_response = {
                            "error": "Invalid JSON in request",
                            "status": "error"
                        }
                        response_data = json.dumps(error_response).encode('utf-8')
                        writer.write(b'HTTP/1.1 400 Bad Request\r\n')
                        writer.write(b'Content-Type: application/json; charset=utf-8\r\n')
                        writer.write(f'Content-Length: {len(response_data)}\r\n'.encode('utf-8'))
                        writer.write(b'\r\n')
                        writer.write(response_data)
                        await writer.drain()
                    except UnicodeDecodeError as e:
                        logger.error(f"Error decoding request data: {e}")
                        error_response = {
                            "error": "Invalid character encoding in request",
                            "status": "error"
                        }
                        response_data = json.dumps(error_response).encode('utf-8')
                        writer.write(b'HTTP/1.1 400 Bad Request\r\n')
                        writer.write(b'Content-Type: application/json; charset=utf-8\r\n')
                        writer.write(f'Content-Length: {len(response_data)}\r\n'.encode('utf-8'))
                        writer.write(b'\r\n')
                        writer.write(response_data)
                        await writer.drain()
                else:
                    logger.warning("No content length in request")
                    error_response = {
                        "error": "No content length specified",
                        "status": "error"
                    }
                    response_data = json.dumps(error_response).encode('utf-8')
                    writer.write(b'HTTP/1.1 400 Bad Request\r\n')
                    writer.write(b'Content-Type: application/json; charset=utf-8\r\n')
                    writer.write(f'Content-Length: {len(response_data)}\r\n'.encode('utf-8'))
                    writer.write(b'\r\n')
                    writer.write(response_data)
                    await writer.drain()
                
            except ConnectionResetError as e:
                logger.warning(f"Connection reset by peer: {e}")
                return
            except Exception as e:
                logger.error(f"Error handling HTTP connection: {e}")
                try:
                    error_response = {
                        "error": str(e),
                        "status": "error"
                    }
                    response_data = json.dumps(error_response).encode('utf-8')
                    writer.write(b'HTTP/1.1 500 Internal Server Error\r\n')
                    writer.write(b'Content-Type: application/json; charset=utf-8\r\n')
                    writer.write(f'Content-Length: {len(response_data)}\r\n'.encode('utf-8'))
                    writer.write(b'\r\n')
                    writer.write(response_data)
                    await writer.drain()
                except Exception as write_error:
                    logger.error(f"Error sending error response: {write_error}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception as e:
                logger.error(f"Error closing connection: {e}")

    async def _run_stdio(self):
        """Run the server in stdio mode."""
        try:
            # Initialize the server first
            await self.initialize(ClientInfo())
            
            while True:
                try:
                    # Read a line from stdin
                    line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                    if not line:
                        break
                    
                    # Parse the request
                    request = json.loads(line)
                    logger.debug(f"Received request: {request}")
                    
                    # Process the request
                    response = await self.process_request(request)
                    
                    # Send the response
                    print(json.dumps(response), flush=True)
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON: {e}")
                    error_response = {
                        "error": "Invalid JSON",
                        "status": "error"
                    }
                    print(json.dumps(error_response), flush=True)
                except Exception as e:
                    logger.error(f"Error processing request: {e}")
                    error_response = {
                        "error": str(e),
                        "status": "error"
                    }
                    print(json.dumps(error_response), flush=True)
                    
        except Exception as e:
            logger.error(f"Error in stdio server: {e}")
            raise

    async def process_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Process a JSON-RPC request."""
        try:
            # Check if this is a custom tool format (array with tool objects)
            if isinstance(request, list) and len(request) > 0:
                # Handle custom tool format
                tool_request = request[0]
                if isinstance(tool_request, dict) and "tool" in tool_request:
                    # Convert to standard format
                    tool_name = tool_request["tool"]
                    tool_params = tool_request.get("params", {})
                    
                    # Create a standard JSON-RPC request
                    standard_request = {
                        "jsonrpc": "2.0",
                        "method": "call_tool",
                        "params": {
                            "name": tool_name,
                            "arguments": tool_params
                        },
                        "id": None
                    }
                    
                    # Process as standard request
                    return await self._process_standard_request(standard_request)
            
            # Process as standard JSON-RPC request
            return await self._process_standard_request(request)
            
        except Exception as e:
            logger.error(f"Error processing request: {str(e)}")
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": str(e)
                },
                "id": request.get("id") if isinstance(request, dict) else None
            }

    async def _process_standard_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Process a standard JSON-RPC request."""
        try:
            # Parse request
            jsonrpc_request = JsonRpcRequest.from_dict(request)
            # PATCH: alias per compatibilità n8n
            method_aliases = {
                "tools/list": "list_tools",
                "prompts/list": "list_prompts",
                "resources/templates/list": "list_resource_templates",
                "resources/list": "list_resources",
                "resources/read": "get_resource",
                "notifications/initialized": "handle_notification_initialized",
                "tools/call": "call_tool"
            }
            method = jsonrpc_request.method
            if method in method_aliases:
                jsonrpc_request.method = method_aliases[method]
            # Handle different methods
            if jsonrpc_request.method == "initialize":
                return await self._handle_initialize(jsonrpc_request)
            elif jsonrpc_request.method == "list_resources":
                return await self._handle_list_resources(jsonrpc_request)
            elif jsonrpc_request.method == "list_tools":
                return await self._handle_list_tools(jsonrpc_request)
            elif jsonrpc_request.method == "list_prompts":
                return await self._handle_list_prompts(jsonrpc_request)
            elif jsonrpc_request.method == "get_prompt":
                return await self._handle_get_prompt(jsonrpc_request)
            elif jsonrpc_request.method == "list_resource_templates":
                return await self._handle_list_resource_templates(jsonrpc_request)
            elif jsonrpc_request.method == "get_resource":
                return await self._handle_get_resource(jsonrpc_request)
            elif jsonrpc_request.method == "handle_notification_initialized":
                return await self._handle_notification_initialized(jsonrpc_request)
            elif jsonrpc_request.method == "call_tool":
                # Handle tool calls
                tool_name = jsonrpc_request.params.get("name")
                tool_args = jsonrpc_request.params.get("arguments", {})
                
                if tool_name == "odoo_search_read":
                    # Get parameters
                    model = tool_args.get("model")
                    # Extract domain and fields from kwargs if they exist
                    kwargs = tool_args.get("kwargs", {})
                    domain = kwargs.get("domain", tool_args.get("domain", []))
                    fields = kwargs.get("fields", tool_args.get("fields", ["id", "name"]))
                    limit = kwargs.get("limit", tool_args.get("limit", 100))
                    offset = kwargs.get("offset", tool_args.get("offset", 0))
                    
                    # Create URI for the list resource
                    uri = f"odoo://{model}/list"
                    
                    # Get resource with search parameters
                    resource = await self._handle_odoo_record_list(
                        uri=uri,
                        model=model,
                        domain=domain,
                        fields=fields,
                        limit=limit,
                        offset=offset
                    )
                    # Trasforma ogni record in formato compatibile con n8n/langchain
                    content = [
                        {
                            "type": "text",
                            "text": ", ".join([f"{k}: {v}" for k, v in record.items()])
                        }
                        for record in resource.content
                    ]
                    return {
                        "jsonrpc": "2.0",
                        "result": {
                            "content": content,
                            "metadata": resource.metadata
                        },
                        "id": jsonrpc_request.id
                    }
                elif tool_name == "odoo_read":
                    model = tool_args.get("model")
                    # Extract parameters from args and kwargs
                    args = tool_args.get("args", [])
                    kwargs = tool_args.get("kwargs", {})
                    ids = args[0] if args else tool_args.get("ids", [])
                    # For read, fields are in args[1], not in kwargs
                    fields = args[1] if len(args) > 1 else (kwargs.get("fields", tool_args.get("fields", ["id", "name"])))
                    records = await self.pool.execute_kw(
                        model=model,
                        method="read",
                        args=[ids, fields],
                        kwargs={}
                    )
                    # Trasforma in formato compatibile se records è una lista di dict
                    if isinstance(records, list) and records and isinstance(records[0], dict):
                        content = [
                            {
                                "type": "text",
                                "text": ", ".join([f"{k}: {v}" for k, v in record.items()])
                            }
                            for record in records
                        ]
                    else:
                        content = records
                    return {
                        "jsonrpc": "2.0",
                        "result": {
                            "content": content,
                            "metadata": {
                                "model": model,
                                "count": len(records)
                            }
                        },
                        "id": jsonrpc_request.id
                    }
                elif tool_name == "odoo_write":
                    model = tool_args.get("model")
                    # Extract parameters from args and kwargs
                    args = tool_args.get("args", [])
                    kwargs = tool_args.get("kwargs", {})
                    ids = args[0] if args else tool_args.get("ids", [])
                    # For write, values are in args[1], not in kwargs
                    values = args[1] if len(args) > 1 else (kwargs if kwargs else tool_args.get("values", {}))
                    result = await self.pool.execute_kw(
                        model=model,
                        method="write",
                        args=[ids, values],
                        kwargs={}
                    )
                    # result può essere bool o lista, gestiamo entrambi
                    if isinstance(result, list) and result and isinstance(result[0], dict):
                        content = [
                            {
                                "type": "text",
                                "text": ", ".join([f"{k}: {v}" for k, v in record.items()])
                            }
                            for record in result
                        ]
                    else:
                        content = [{"type": "text", "text": str(result)}]
                    return {
                        "jsonrpc": "2.0",
                        "result": {
                            "content": content,
                            "metadata": {
                                "model": model,
                                "operation": "write"
                            }
                        },
                        "id": jsonrpc_request.id
                    }
                elif tool_name == "odoo_unlink":
                    model = tool_args.get("model")
                    # Extract parameters from args
                    args = tool_args.get("args", [])
                    ids = args[0] if args else tool_args.get("ids", [])
                    result = await self.pool.execute_kw(
                        model=model,
                        method="unlink",
                        args=[ids],
                        kwargs={}
                    )
                    content = [{"type": "text", "text": str(result)}]
                    return {
                        "jsonrpc": "2.0",
                        "result": {
                            "content": content,
                            "metadata": {
                                "model": model,
                                "operation": "unlink"
                            }
                        },
                        "id": jsonrpc_request.id
                    }
                elif tool_name == "odoo_call_method":
                    model = tool_args.get("model")
                    # Extract method from tool_args or kwargs
                    method = tool_args.get("method")
                    if not method:
                        # Try to get method from kwargs
                        kwargs = tool_args.get("kwargs", {})
                        method = kwargs.get("method")
                    
                    # Extract parameters from args and kwargs
                    args = tool_args.get("args", [])
                    kwargs = tool_args.get("kwargs", {})
                    
                    # For call_method, we need to handle different cases:
                    if method == "search_read":
                        # For search_read method: domain and fields can come from args or kwargs
                        if args and len(args) >= 2:
                            # Parameters in args: args[0] = domain, args[1] = fields
                            domain = args[0]
                            fields = args[1]
                        else:
                            # Parameters in kwargs
                            domain = kwargs.get("domain", [])
                            fields = kwargs.get("fields", ["id", "name"])
                        method_args = [domain, fields]
                        method_kwargs = {}
                    elif method == "read":
                        # For read method: args[0] = IDs, args[1] = fields
                        ids = args[0] if args else []
                        fields = args[1] if len(args) > 1 else ["id", "name"]
                        method_args = [ids, fields]
                        method_kwargs = kwargs if kwargs else {}
                    elif method in ["write", "unlink"]:
                        # For these methods, args[0] contains IDs, values are in kwargs
                        ids = args[0] if args else []
                        method_args = [ids]  # IDs as first argument
                        method_kwargs = kwargs if kwargs else {}
                    else:
                        # For other methods, args[0] = IDs, args[1:] = additional method args
                        ids = args[0] if args else []
                        additional_args = args[1:] if len(args) > 1 else []
                        method_args = [ids] + additional_args
                        method_kwargs = kwargs if kwargs else {}
                    
                    result = await self.pool.execute_kw(
                        model=model,
                        method=method,
                        args=method_args,
                        kwargs=method_kwargs
                    )
                    # Se il risultato è una lista di dict, trasforma
                    if isinstance(result, list) and result and isinstance(result[0], dict):
                        content = [
                            {
                                "type": "text",
                                "text": ", ".join([f"{k}: {v}" for k, v in record.items()])
                            }
                            for record in result
                        ]
                    else:
                        content = [{"type": "text", "text": str(result)}]
                    return {
                        "jsonrpc": "2.0",
                        "result": {
                            "content": content,
                            "metadata": {
                                "model": model,
                                "method": method
                            }
                        },
                        "id": jsonrpc_request.id
                    }
                elif tool_name == "odoo_execute_kw":
                    model = tool_args.get("model")
                    # Extract method from tool_args or kwargs
                    method = tool_args.get("method")
                    if not method:
                        # Try to get method from kwargs
                        kwargs_ = tool_args.get("kwargs", {})
                        method = kwargs_.get("method")
                    
                    # Extract parameters from args and kwargs
                    args = tool_args.get("args", [])
                    kwargs_ = tool_args.get("kwargs", {})
                    
                    # For execute_kw, we need to handle different cases:
                    if method == "search_read":
                        # For search_read method: domain and fields can come from args or kwargs
                        if args and len(args) >= 2:
                            # Parameters in args: args[0] = domain, args[1] = fields
                            domain = args[0]
                            fields = args[1]
                        else:
                            # Parameters in kwargs
                            domain = kwargs_.get("domain", [])
                            fields = kwargs_.get("fields", ["id", "name"])
                        method_args = [domain, fields]
                        method_kwargs = {}
                    elif method == "read":
                        # For read method: args[0] = IDs, args[1] = fields
                        ids = args[0] if args else []
                        fields = args[1] if len(args) > 1 else ["id", "name"]
                        method_args = [ids, fields]
                        method_kwargs = kwargs_ if kwargs_ else {}
                    elif method in ["write", "unlink"]:
                        # For these methods, args[0] contains IDs, values are in kwargs
                        ids = args[0] if args else []
                        method_args = [ids]  # IDs as first argument
                        method_kwargs = kwargs_ if kwargs_ else {}
                    else:
                        # For other methods, args[0] = IDs, args[1:] = additional method args
                        ids = args[0] if args else []
                        additional_args = args[1:] if len(args) > 1 else []
                        method_args = [ids] + additional_args
                        method_kwargs = kwargs_ if kwargs_ else {}
                    
                    result = await self.pool.execute_kw(
                        model=model,
                        method=method,
                        args=method_args,
                        kwargs=method_kwargs
                    )
                    if isinstance(result, list) and result and isinstance(result[0], dict):
                        content = [
                            {
                                "type": "text",
                                "text": ", ".join([f"{k}: {v}" for k, v in record.items()])
                            }
                            for record in result
                        ]
                    else:
                        content = [{"type": "text", "text": str(result)}]
                    return {
                        "jsonrpc": "2.0",
                        "result": {
                            "content": content,
                            "metadata": {
                                "model": model,
                                "method": method
                            }
                        },
                        "id": jsonrpc_request.id
                    }
                elif tool_name == "odoo_create":
                    model = tool_args.get("model")
                    # Extract parameters from args and kwargs
                    args = tool_args.get("args", [])
                    kwargs = tool_args.get("kwargs", {})
                    values = args[0] if args else (kwargs if kwargs else tool_args.get("values", {}))
                    result = await self.pool.execute_kw(
                        model=model,
                        method="create",
                        args=[values],
                        kwargs={}
                    )
                    content = [
                        {"type": "text", "text": str(result)}
                    ]
                    return {
                        "jsonrpc": "2.0",
                        "result": {
                            "content": content,
                            "metadata": {
                                "model": model,
                                "operation": "create"
                            }
                        },
                        "id": jsonrpc_request.id
                    }
                elif tool_name in ["data_export", "data_import", "report_generator"]:
                    return {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32001,
                            "message": f"Tool '{tool_name}' not implemented yet."
                        },
                        "id": jsonrpc_request.id
                    }
                else:
                    raise ProtocolError(f"Unknown tool: {tool_name}")
            else:
                raise ProtocolError(f"Unknown method: {jsonrpc_request.method}")
        except Exception as e:
            logger.error(f"Error processing request: {str(e)}")
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": str(e)
                },
                "id": request.get("id")
            }

    async def _handle_notification_initialized(self, request: JsonRpcRequest) -> Dict[str, Any]:
        """Handle notification initialized request."""
        try:
            logger.info("Received notification initialized request")
            return {
                "jsonrpc": "2.0",
                "result": {
                    "status": "ok"
                },
                "id": request.id
            }
        except Exception as e:
            logger.error(f"Error handling notification initialized: {e}")
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": str(e)
                },
                "id": request.id
            }

    async def _handle_initialize(self, request: JsonRpcRequest) -> Dict[str, Any]:
        """Handle initialize request."""
        try:
            client_info = ClientInfo.from_dict(request.params)
            server_info = await self.initialize(client_info)
            
            # Get the client's requested protocol version
            client_version = request.params.get('protocolVersion', PROTOCOL_VERSION)
            logger.debug(f"Client requested protocol version: {client_version}")
            
            # Use client's version if it's a supported legacy version
            response_version = client_version if client_version in LEGACY_PROTOCOL_VERSIONS else PROTOCOL_VERSION
            logger.debug(f"Using protocol version in response: {response_version}")
            
            # Create response directly
            response = {
                "jsonrpc": "2.0",
                "id": request.id,
                "result": {
                    "protocolVersion": response_version,
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION
                    },
                    "capabilities": server_info.capabilities
                }
            }
            
            logger.debug(f"Initializing client with protocol version: {response_version}")
            return response
            
        except Exception as e:
            logger.error(f"Error handling initialize request: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }

    async def _handle_list_resources(self, request: JsonRpcRequest) -> Dict[str, Any]:
        """Handle list_resources request."""
        try:
            resources = await self.list_resources()
            # Convert to MCP client format with text or blob
            resources_list = []
            for resource in resources:
                if isinstance(resource.content, (dict, list)):
                    # For dictionaries and lists, always use text with JSON
                    content = {
                        "text": json.dumps(resource.content),
                        "blob": None
                    }
                elif isinstance(resource.content, bytes):
                    # For binary content, encode as base64
                    content = {
                        "text": None,
                        "blob": base64.b64encode(resource.content).decode()
                    }
                else:
                    # For other types, convert to string
                    content = {
                        "text": str(resource.content),
                        "blob": None
                    }
                
                # Extract model name from URI for the name field
                uri_parts = resource.uri.replace("odoo://", "").split("/")
                model_name = uri_parts[0] if uri_parts else "unknown"
                
                resources_list.append({
                    "uri": resource.uri,
                    "type": resource.type,
                    "content": resource.content,
                    "mimeType": resource.mime_type,
                    "name": model_name,
                    **content
                })
            
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "result": {
                    "id": "list",
                    "method": "listResources",
                    "resources": resources_list
                }
            }
        except Exception as e:
            logger.error(f"Error handling list_resources request: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }

    async def _handle_list_tools(self, request: JsonRpcRequest) -> Dict[str, Any]:
        """Handle list_tools request."""
        try:
            tools = await self.list_tools()
            return {
                'jsonrpc': '2.0',
                'id': request.id,
                'result': {
                    'tools': [
                        {
                            'name': tool.name,
                            'description': tool.description,
                            'parameters': tool.parameters,
                            'inputSchema': tool.inputSchema or {
                                'type': 'object',
                                'properties': {},
                                'required': []
                            }
                        }
                        for tool in tools
                    ]
                }
            }
        except Exception as e:
            logger.error(f"Error handling list_tools request: {e}")
            return {
                'jsonrpc': '2.0',
                'id': request.id,
                'error': {
                    'code': -32603,
                    'message': f"Internal error: {str(e)}"
                }
            }

    async def _handle_get_prompt(self, request: JsonRpcRequest) -> Dict[str, Any]:
        """Handle get_prompt request."""
        try:
            prompt = await self.get_prompt(
            request.params['name'],
            request.params.get('args', {})
            )
            # Convert ProtocolHandler response to dict
            response = self.protocol_handler.create_response(
            request.id,
            result=prompt
            )
            response = response.model_dump() if hasattr(response, 'model_dump') else dict(response)
            if 'error' in response and (response['error'] is None or response['error'] == {}):
                del response['error']
            return response
        except Exception as e:
            logger.error(f"Error handling get_prompt request: {e}")
            error_response = self.protocol_handler.handle_protocol_error(e)
            error_response = error_response.model_dump() if hasattr(error_response, 'model_dump') else dict(error_response)
            if 'error' in error_response and (error_response['error'] is None or error_response['error'] == {}):
                del error_response['error']
            return error_response

    async def stop(self):
        """Stop the server and clean up resources."""
        try:
            logger.info("Stopping server...")
            self.running = False
            
            # Stop the protocol
            if hasattr(self, 'protocol'):
                logger.info("Stopping protocol...")
                self.protocol.stop()
            
            # Close the connection pool
            if hasattr(self, 'pool'):
                logger.info("Closing connection pool...")
                await self.pool.close()
            
            # Stop the bus handler
            if hasattr(self, 'bus_handler'):
                logger.info("Stopping bus handler...")
                await self.bus_handler.stop()
            
            # Clear the cache
            if hasattr(self, 'resource_manager'):
                logger.info("Clearing resource cache...")
                self.resource_manager.clear_cache()
            
            logger.info("Server stopped successfully")
            
        except Exception as e:
            logger.error(f"Error stopping server: {e}")
            raise

    async def _handle_request(self, request: Union[web.Request, Dict[str, Any]]) -> Union[web.Response, Dict[str, Any]]:
        """Handle incoming requests."""
        try:
            if isinstance(request, web.Request):
                # Handle HTTP request
                data = await request.json()
                logger.debug("Received HTTP request data")
                response = await self.process_request(data)
                logger.debug(f"Got response from process_request: {response}")
                logger.debug(f"Response type: {type(response)}")
                logger.debug(f"Response attributes: {dir(response)}")
                try:
                    # Build JSON-RPC response dict with only 'result' OR 'error'
                    response_dict = {
                        'jsonrpc': getattr(response, 'jsonrpc', '2.0'),
                        'id': getattr(response, 'id', None)
                    }
                    error = getattr(response, 'error', None)
                    if error is not None:
                        response_dict['error'] = error
                    else:
                        response_dict['result'] = getattr(response, 'result', None)
                    logger.debug(f"Converted response dict: {response_dict}")
                    return web.json_response(response_dict)
                except Exception as e:
                    logger.error(f"Error converting response to dict: {e}")
                    logger.exception("Full traceback for conversion error:")
                    return web.json_response({
                        "error": f"Error converting response: {str(e)}",
                        "status": "error"
                    }, status=500)
            else:
                # Handle stdio request
                logger.debug("Received stdio request")
                response = await self.process_request(request)
                logger.debug(f"Got response from process_request: {response}")
                logger.debug(f"Response type: {type(response)}")
                logger.debug(f"Response attributes: {dir(response)}")
                try:
                    # Build JSON-RPC response dict with only 'result' OR 'error'
                    response_dict = {
                        'jsonrpc': getattr(response, 'jsonrpc', '2.0'),
                        'id': getattr(response, 'id', None)
                    }
                    error = getattr(response, 'error', None)
                    if error is not None:
                        response_dict['error'] = error
                    else:
                        response_dict['result'] = getattr(response, 'result', None)
                    logger.debug(f"Converted response dict: {response_dict}")
                    return response_dict
                except Exception as e:
                    logger.error(f"Error converting response to dict: {e}")
                    logger.exception("Full traceback for conversion error:")
                    return {
                        "error": f"Error converting response: {str(e)}",
                        "status": "error"
                    }
        except Exception as e:
            logger.error(f"Error handling request: {e}")
            logger.exception("Full traceback for request handling error:")
            if isinstance(request, web.Request):
                return web.json_response({
                    "error": str(e),
                    "status": "error"
                }, status=500)
            else:
                return {
                    "error": str(e),
                    "status": "error"
                }

def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)

async def main(config_path: str = "odoo_mcp/config/config.dev.yaml"):
    """Main entry point for the server."""
    try:
        # Setup basic logging first
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
            stream=sys.stdout
        )
        logger.info("Starting server initialization...")
        
        # Load configuration
        logger.info(f"Loading configuration from {config_path}")
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info("Configuration loaded successfully")
            logger.debug(f"Configuration content: {config}")
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise
        
        # Setup logging from config
        logger.info("Setting up logging from configuration...")
        try:
            if 'logging' in config:
                logger.info("Found logging configuration in config file")
                setup_logging_from_config(config['logging'])
                logger.info("Logging configured from config file")
            else:
                logger.info("No logging configuration found, using default settings")
                setup_logging(config.get('log_level', 'INFO'))
                logger.info(f"Logging configured with level: {config.get('log_level', 'INFO')}")
        except Exception as e:
            logger.error(f"Failed to setup logging: {e}")
            raise
        
        # Initialize cache manager first
        logger.info("Initializing cache manager...")
        try:
            cache_config = config.get('cache', {})
            logger.info(f"Cache configuration: {cache_config}")
            initialize_cache_manager(config)
            logger.info("Cache manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize cache manager: {e}")
            raise

        # Create server instance
        logger.info("Creating server instance...")
        try:
            server = OdooMCPServer(config)
            logger.info("Server instance created successfully")
        except Exception as e:
            logger.error(f"Failed to create server instance: {e}")
            raise
        
        # Initialize server
        logger.info("Initializing server...")
        try:
            client_info = ClientInfo()
            logger.info(f"Initializing with client info: {client_info}")
            await server.initialize(client_info)
            logger.info("Server initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize server: {e}")
            raise
        
        # Start server
        logger.info("Starting server...")
        try:
            await server.run()
            logger.info("Server started successfully")
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            raise
        
    except Exception as e:
        logger.error(f"Error running server: {e}")
        raise

def main_cli():
    """Command line entry point."""
    parser = argparse.ArgumentParser(description='Odoo MCP Server')
    parser.add_argument('--config', default='odoo_mcp/config/config.json',
                      help='Path to configuration file')
    args = parser.parse_args()

    try:
        # Run the async main function
        asyncio.run(main(args.config))
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main_cli()
