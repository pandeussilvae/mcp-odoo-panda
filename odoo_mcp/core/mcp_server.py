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
from odoo_mcp.core.protocol_handler import ProtocolHandler
from odoo_mcp.core.capabilities_manager import CapabilitiesManager, ResourceTemplate, Tool, Prompt
from odoo_mcp.core.resource_manager import ResourceManager, Resource

# Import MCP components
from mcp_local_backup import (
    Server, ServerInfo, ClientInfo,
    StdioProtocol, SSEProtocol
)

# Constants
SERVER_NAME = "odoo-mcp-server"
SERVER_VERSION = "2024.2.5"  # Using CalVer: YYYY.MM.DD
PROTOCOL_VERSION = "2024-01-01"

logger = logging.getLogger(__name__)

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
        self.config = config
        self.protocol_type = config.get('protocol', 'xmlrpc').lower()
        self.connection_type = config.get('connection_type', 'stdio').lower()

        # Initialize core components
        self.protocol_handler = ProtocolHandler(PROTOCOL_VERSION)
        self.capabilities_manager = CapabilitiesManager()
        self.resource_manager = ResourceManager(
            cache_ttl=config.get('cache_ttl', 300)
        )

        # Initialize Odoo components
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
        # Register Odoo record handler
        self.resource_manager.register_resource_handler(
            "odoo://{model}/{id}",
            self._handle_odoo_record
        )

        # Register Odoo record list handler
        self.resource_manager.register_resource_handler(
            "odoo://{model}/list",
            self._handle_odoo_record_list
        )

        # Register Odoo binary field handler
        self.resource_manager.register_resource_handler(
            "odoo://{model}/binary/{field}/{id}",
            self._handle_odoo_binary_field
        )

    def _register_tools_and_prompts(self) -> None:
        """Register tools and prompts."""
        # Register resource templates
        templates = [
            ResourceTemplate(
                uri_template="odoo://{model}/{id}",
                name="Odoo Record",
                description="Represents a single record in an Odoo model",
                type="record",
                mime_type="application/json"
            ),
            ResourceTemplate(
                uri_template="odoo://{model}/list",
                name="Odoo Record List",
                description="Represents a list of records in an Odoo model",
                type="list",
                mime_type="application/json"
            ),
            ResourceTemplate(
                uri_template="odoo://{model}/binary/{field}/{id}",
                name="Odoo Binary Field",
                description="Represents a binary field value from an Odoo record",
                type="binary",
                mime_type="application/octet-stream"
            )
        ]

        for template in templates:
            self.capabilities_manager.add_resource_template(template)

        # Register tools
        tools = [
            Tool(
                name="odoo_login",
                description="Authenticate with Odoo",
                parameters={
                    "database": {"type": "string", "description": "Database name"},
                    "username": {"type": "string", "description": "Username"},
                    "password": {"type": "string", "description": "Password"}
                },
                returns={
                    "uid": {"type": "integer", "description": "User ID"},
                    "session_id": {"type": "string", "description": "Session ID"}
                }
            ),
            # Add more tools here
        ]

        for tool in tools:
            self.capabilities_manager.add_tool(tool)

        # Register prompts
        prompts = [
            Prompt(
                name="analyze-record",
                description="Analyze an Odoo record",
                parameters={
                    "model": {"type": "string", "description": "Model name"},
                    "id": {"type": "integer", "description": "Record ID"}
                },
                returns={
                    "analysis": {"type": "object", "description": "Record analysis"}
                }
            ),
            # Add more prompts here
        ]

        for prompt in prompts:
            self.capabilities_manager.add_prompt(prompt)

    async def _handle_odoo_record(self, uri: str) -> Resource:
        """Handle Odoo record resource requests."""
        try:
            # Parse URI
            parts = uri.replace("odoo://", "").split("/")
            if len(parts) != 2:
                raise ProtocolError(f"Invalid record URI format: {uri}")
            
            model = parts[0]
            try:
                record_id = int(parts[1])
            except ValueError:
                raise ProtocolError(f"Invalid record ID in URI: {uri}")

            # Get record from Odoo
            record = await self.pool.execute_kw(
                model=model,
                method="read",
                args=[[record_id]],
                kwargs={}
            )

            if not record:
                raise OdooRecordNotFoundError(f"Record {record_id} not found in model {model}")

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
            raise ProtocolError(f"Error handling Odoo record request: {str(e)}")

    async def _handle_odoo_record_list(self, uri: str) -> Resource:
        """Handle Odoo record list resource requests."""
        try:
            # Parse URI
            parts = uri.replace("odoo://", "").split("/")
            if len(parts) != 2 or parts[1] != "list":
                raise ProtocolError(f"Invalid record list URI format: {uri}")
            
            model = parts[0]

            # Get records from Odoo
            records = await self.pool.execute_kw(
                model=model,
                method="search_read",
                args=[[], ["id", "name"]],
                kwargs={"limit": 100}
            )

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

        except Exception as e:
            if isinstance(e, ProtocolError):
                raise
            raise ProtocolError(f"Error handling Odoo record list request: {str(e)}")

    async def _handle_odoo_binary_field(self, uri: str) -> Resource:
        """Handle Odoo binary field resource requests."""
        try:
            # Parse URI
            parts = uri.replace("odoo://", "").split("/")
            if len(parts) != 4 or parts[1] != "binary":
                raise ProtocolError(f"Invalid binary field URI format: {uri}")
            
            model = parts[0]
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
        # Validate protocol version
        if not self.protocol_handler.validate_protocol_version(client_info.protocol_version):
            raise ProtocolError(f"Unsupported protocol version: {client_info.protocol_version}")

        # Create server info
        return ServerInfo(
            name=SERVER_NAME,
            version=SERVER_VERSION,
            capabilities=self.capabilities
        )

    async def get_resource(self, uri: str) -> Resource:
        """Get a resource by URI."""
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
                return [
                    Resource(
                        uri=template.uri_template,
                        type=template.type,
                        content=None,
                        mime_type=template.mime_type,
                        metadata={
                            "name": template.name,
                            "description": template.description
                        }
                    )
                    for template in self.capabilities_manager._resource_templates
                ]

        except Exception as e:
            if isinstance(e, ProtocolError):
                raise
            raise ProtocolError(f"Error listing resources: {str(e)}")

    async def list_tools(self) -> List[Tool]:
        """List available tools."""
        return self.capabilities_manager._tools

    async def list_prompts(self) -> List[Prompt]:
        """List available prompts."""
        return self.capabilities_manager._prompts

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

    async def run(self):
        """Run the server."""
        if self.connection_type == 'stdio':
            logger.info("Starting server in stdio mode")
            await self.protocol.run()
        elif self.connection_type == 'sse':
            host = self.config.get('host', 'localhost')
            port = self.config.get('port', 8080)
            logger.info(f"Starting server in SSE mode on http://{host}:{port}")
            await self.protocol.run(host=host, port=port)

    async def stop(self):
        """Stop the server."""
        self.protocol.stop()
        await super().stop()

    def _handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle incoming requests."""
        try:
            # Parse and validate request
            parsed_request = self.protocol_handler.parse_request(request)
            
            # Handle the request based on method
            if parsed_request.method == 'initialize':
                return self._handle_initialize(parsed_request)
            elif parsed_request.method == 'get_resource':
                return self._handle_get_resource(parsed_request)
            elif parsed_request.method == 'list_resources':
                return self._handle_list_resources(parsed_request)
            elif parsed_request.method == 'list_tools':
                return self._handle_list_tools(parsed_request)
            elif parsed_request.method == 'list_prompts':
                return self._handle_list_prompts(parsed_request)
            elif parsed_request.method == 'get_prompt':
                return self._handle_get_prompt(parsed_request)
            else:
                return self.protocol_handler.create_error_response(
                    parsed_request.id,
                    -32601,
                    f"Method not found: {parsed_request.method}"
                )

        except Exception as e:
            return self.protocol_handler.handle_protocol_error(e)

    def _handle_initialize(self, request: JsonRpcRequest) -> Dict[str, Any]:
        """Handle initialize request."""
        client_info = ClientInfo.from_dict(request.params)
        server_info = run_async(self.initialize(client_info))
        return self.protocol_handler.create_response(
            request.id,
            result={
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION
                },
                "capabilities": server_info.capabilities
            }
        )

    def _handle_get_resource(self, request: JsonRpcRequest) -> Dict[str, Any]:
        """Handle get_resource request."""
        resource = run_async(self.get_resource(request.params['uri']))
        return self.protocol_handler.create_response(
            request.id,
            result=resource
        )

    def _handle_list_resources(self, request: JsonRpcRequest) -> Dict[str, Any]:
        """Handle list_resources request."""
        resources = run_async(self.list_resources())
        return self.protocol_handler.create_response(
            request.id,
            result={'resources': resources}
        )

    def _handle_list_tools(self, request: JsonRpcRequest) -> Dict[str, Any]:
        """Handle list_tools request."""
        tools = run_async(self.list_tools())
        return self.protocol_handler.create_response(
            request.id,
            result={'tools': tools}
        )

    def _handle_list_prompts(self, request: JsonRpcRequest) -> Dict[str, Any]:
        """Handle list_prompts request."""
        prompts = run_async(self.list_prompts())
        return self.protocol_handler.create_response(
            request.id,
            result={'prompts': prompts}
        )

    def _handle_get_prompt(self, request: JsonRpcRequest) -> Dict[str, Any]:
        """Handle get_prompt request."""
        prompt = run_async(self.get_prompt(
            request.params['name'],
            request.params.get('args', {})
        ))
        return self.protocol_handler.create_response(
            request.id,
            result=prompt
        )

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
