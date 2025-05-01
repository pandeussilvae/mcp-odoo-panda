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

# Import MCP components
from mcp_local_backup import (
    Server, Resource, Tool, Prompt,
    ServerInfo, ClientInfo, ResourceTemplate,
    GetPromptResult, PromptMessage, TextContent,
    ResourceType, StdioProtocol, SSEProtocol
)

# Constants
SERVER_NAME = "odoo-mcp-server"
SERVER_VERSION = "2024.2.5"  # Using CalVer: YYYY.MM.DD
PROTOCOL_VERSION = "2024-01-01"  # Protocol version in YYYY-MM-DD format

# Resource Templates
RESOURCE_TEMPLATES = [
    {
        "uriTemplate": "odoo://{model}/{id}",
        "name": "Odoo Record",
        "description": "Represents a single record in an Odoo model",
        "type": "record",
        "mimeType": "application/json"
    },
    {
        "uriTemplate": "odoo://{model}/list",
        "name": "Odoo Record List",
        "description": "Represents a list of records in an Odoo model",
        "type": "list",
        "mimeType": "application/json"
    },
    {
        "uriTemplate": "odoo://{model}/binary/{field}/{id}",
        "name": "Odoo Binary Field",
        "description": "Represents a binary field value from an Odoo record",
        "type": "binary",
        "mimeType": "application/octet-stream"
    }
]

# Tool Definitions
TOOLS = {
    "odoo_search_read": {
        "description": "Search and read records from an Odoo model",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model name"},
                "domain": {"type": "array", "description": "Search domain"},
                "fields": {"type": "array", "description": "Fields to read"},
                "limit": {"type": "integer", "description": "Limit number of records"},
                "offset": {"type": "integer", "description": "Offset for pagination"},
                "context": {"type": "object", "description": "Context dictionary"}
            },
            "required": ["model"]
        }
    },
    "odoo_read": {
        "description": "Read specific records from an Odoo model",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model name"},
                "ids": {"type": "array", "description": "Record IDs to read"},
                "fields": {"type": "array", "description": "Fields to read"},
                "context": {"type": "object", "description": "Context dictionary"}
            },
            "required": ["model", "ids"]
        }
    },
    "odoo_create": {
        "description": "Create a new record in an Odoo model",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model name"},
                "values": {"type": "object", "description": "Values for the new record"},
                "context": {"type": "object", "description": "Context dictionary"}
            },
            "required": ["model", "values"]
        }
    },
    "odoo_write": {
        "description": "Update existing records in an Odoo model",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model name"},
                "ids": {"type": "array", "description": "Record IDs to update"},
                "values": {"type": "object", "description": "Values to update"},
                "context": {"type": "object", "description": "Context dictionary"}
            },
            "required": ["model", "ids", "values"]
        }
    },
    "odoo_unlink": {
        "description": "Delete records from an Odoo model",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model name"},
                "ids": {"type": "array", "description": "Record IDs to delete"},
                "context": {"type": "object", "description": "Context dictionary"}
            },
            "required": ["model", "ids"]
        }
    },
    "odoo_call_method": {
        "description": "Call a custom method on an Odoo model",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model name"},
                "method": {"type": "string", "description": "Method name"},
                "args": {"type": "array", "description": "Method arguments"},
                "kwargs": {"type": "object", "description": "Method keyword arguments"},
                "context": {"type": "object", "description": "Context dictionary"}
            },
            "required": ["model", "method"]
        }
    }
}

# Prompt Definitions
PROMPTS = {
    "analyze-record": {
        "description": "Analyze an Odoo record and provide insights",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uri": {"type": "string", "description": "URI of the record to analyze"}
            },
            "required": ["uri"]
        }
    },
    "create-record": {
        "description": "Create a new record with guided field selection",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model name"},
                "template": {"type": "object", "description": "Optional template to pre-fill fields"}
            },
            "required": ["model"]
        }
    },
    "update-record": {
        "description": "Update an existing record with guided field selection",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uri": {"type": "string", "description": "URI of the record to update"}
            },
            "required": ["uri"]
        }
    },
    "advanced-search": {
        "description": "Perform an advanced search with domain builder",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model name"},
                "fields": {"type": "array", "description": "Fields to return in results"}
            },
            "required": ["model"]
        }
    },
    "call-method": {
        "description": "Call a method on records with guided parameter selection",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uri": {"type": "string", "description": "URI of the record or model name"},
                "method": {"type": "string", "description": "Name of the method to call"}
            },
            "required": ["uri", "method"]
        }
    }
}

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
        super().__init__(SERVER_NAME, SERVER_VERSION)
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

        # Test Odoo connection on startup e acquisizione UID reale
        try:
            handler = self.pool.handler_class(config)
            version = handler.common.version()
            print(f"[MCP] Connessione a Odoo OK. Versione: {version}", file=sys.stderr)
            # Autenticazione per ottenere l'uid reale
            db = config.get('db') or config.get('database')
            if not db:
                print("[MCP] ERRORE: parametro 'db' (o 'database') mancante nella configurazione!", file=sys.stderr)
                raise ConfigurationError("Parametro 'db' (o 'database') mancante nella configurazione.")
            print(f"[MCP] Database usato per autenticazione: {db}", file=sys.stderr)
            username = config.get('username')
            password = config.get('api_key') or config.get('password')
            uid = handler.common.authenticate(db, username, password, {})
            if not uid:
                print(f"[MCP] Autenticazione Odoo FALLITA per {username} su {db}", file=sys.stderr)
            else:
                print(f"[MCP] Autenticazione Odoo OK: username={username}, uid={uid}", file=sys.stderr)
                config['uid'] = uid  # Salva l'uid reale nel config
        except Exception as e:
            print(f"[MCP] Connessione a Odoo FALLITA: {e}", file=sys.stderr)

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
                "listChanged": True,
                "resources": {template["uriTemplate"]: template for template in RESOURCE_TEMPLATES},
                "subscribe": False
            },
            "tools": {
                "listChanged": True,
                "tools": TOOLS
            },
            "prompts": {
                "listChanged": True,
                "prompts": PROMPTS
            },
            "experimental": {}
        }

    async def initialize(self, client_info: ClientInfo) -> ServerInfo:
        """Handle initialization request."""
        # Get current capabilities
        current_capabilities = self.capabilities
        print(f"[DEBUG] Current capabilities: {json.dumps(current_capabilities, indent=2)}", file=sys.stderr)
        
        # Create server info with proper capabilities
        server_info = ServerInfo(
            name=SERVER_NAME,
            version=SERVER_VERSION,
            capabilities=current_capabilities
        )
        
        # Log the server info for debugging
        print(f"[DEBUG] Server info: {json.dumps(server_info.__dict__, indent=2)}", file=sys.stderr)
        
        return server_info

    async def get_resource(self, uri: str) -> dict:
        """Get a resource by URI."""
        # Se l'URI contiene placeholder, restituisci un template vuoto
        if "{model}" in uri or "{id}" in uri or "{field}" in uri:
            return {
                "uri": uri,
                "type": "record",  # o il tipo appropriato basato sull'URI
                "name": "Template Resource",
                "contents": [],  # Array vuoto per template
                "mime_type": "application/json"
            }

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
            return {
                "uri": uri,
                "type": "list",
                "name": f"{model_name} List",
                "contents": [
                    {
                        "type": "text",
                        "text": json.dumps(data, indent=2)
                    }
                ],
                "mime_type": "application/json"
            }
        elif parts[1] == "binary":
            # Binary field
            if len(parts) != 4:
                raise ProtocolError(f"Invalid binary field URI format: {uri}")
            model_name, _, field_name, id_str = parts
            data = await self._handle_binary_resource(model_name, field_name, id_str, auth_details)
            return {
                "uri": uri,
                "type": "binary",
                "name": f"{model_name} {field_name}",
                "contents": [
                    {
                        "type": "binary",
                        "data": data
                    }
                ],
                "mime_type": "application/octet-stream"
            }
        else:
            # Single record
            if len(parts) != 2:
                raise ProtocolError(f"Invalid record URI format: {uri}")
            model_name, id_str = parts
            data = await self._handle_record_resource(model_name, id_str, auth_details)
            return {
                "uri": uri,
                "type": "record",
                "name": f"{model_name} {id_str}",
                "contents": [
                    {
                        "type": "text",
                        "text": json.dumps(data, indent=2)
                    }
                ],
                "mime_type": "application/json"
            }

    async def list_resources(self, template: Optional[ResourceTemplate] = None) -> List[dict]:
        """List available resources."""
        return [
            {
                "uriTemplate": "odoo://{model}/{id}",
                "name": "Odoo Record",
                "description": "Represents a single record in an Odoo model",
                "type": "record",
                "mimeType": "application/json"
            },
            {
                "uriTemplate": "odoo://{model}/list",
                "name": "Odoo Record List",
                "description": "Represents a list of records in an Odoo model",
                "type": "list",
                "mimeType": "application/json"
            },
            {
                "uriTemplate": "odoo://{model}/binary/{field}/{id}",
                "name": "Odoo Binary Field",
                "description": "Represents a binary field value from an Odoo record",
                "type": "binary",
                "mimeType": "application/octet-stream"
            }
        ]

    async def list_tools(self) -> List[dict]:
        """List available tools."""
        return [
            {
                "name": "odoo_search_read",
                "description": "Search and read Odoo records",
                "inputSchema": {
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
            },
            {
                "name": "odoo_read",
                "description": "Read specific fields for given Odoo record IDs",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "ids": {"type": "array", "items": {"type": "integer"}},
                        "fields": {"type": "array", "items": {"type": "string"}},
                        "context": {"type": "object", "default": {}}
                    },
                    "required": ["model", "ids"]
                }
            },
            {
                "name": "odoo_create",
                "description": "Create a new record in an Odoo model",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "values": {"type": "object"},
                        "context": {"type": "object", "default": {}}
                    },
                    "required": ["model", "values"]
                }
            },
            {
                "name": "odoo_write",
                "description": "Update existing Odoo records",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "ids": {"type": "array", "items": {"type": "integer"}},
                        "values": {"type": "object"},
                        "context": {"type": "object", "default": {}}
                    },
                    "required": ["model", "ids", "values"]
                }
            },
            {
                "name": "odoo_unlink",
                "description": "Delete Odoo records",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "ids": {"type": "array", "items": {"type": "integer"}},
                        "context": {"type": "object", "default": {}}
                    },
                    "required": ["model", "ids"]
                }
            },
            {
                "name": "odoo_call_method",
                "description": "Call a specific method on Odoo records",
                "inputSchema": {
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
            }
        ]

    async def list_prompts(self) -> List[dict]:
        """List available prompts."""
        return [
            {
                "name": "analyze-record",
                "description": "Analyze an Odoo record and provide insights",
                "arguments": [
                    {
                        "name": "uri",
                        "description": "URI of the record to analyze (e.g., odoo://res.partner/123)",
                        "required": True
                    }
                ]
            },
            {
                "name": "create-record",
                "description": "Create a new record with guided field selection",
                "arguments": [
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
            },
            {
                "name": "update-record",
                "description": "Update an existing record with guided field selection",
                "arguments": [
                    {
                        "name": "uri",
                        "description": "URI of the record to update (e.g., odoo://res.partner/123)",
                        "required": True
                    }
                ]
            },
            {
                "name": "advanced-search",
                "description": "Perform an advanced search with domain builder",
                "arguments": [
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
            },
            {
                "name": "call-method",
                "description": "Call a method on records with guided parameter selection",
                "arguments": [
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
            }
        ]

    async def get_prompt(self, name: str, args: Dict[str, Any]) -> GetPromptResult:
        """Get a prompt by name."""
        # Find the prompt
        prompt = next((p for p in await self.list_prompts() if p['name'] == name), None)
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
            print("[MCP] Server avviato in modalità STDIO (comunicazione tramite stdin/stdout)", file=sys.stderr)
            await self.protocol.run()
        elif self.connection_type == 'sse':
            host = self.config.get('host', 'localhost')
            port = self.config.get('port', 8080)
            print(f"[MCP] Server avviato in modalità SSE su http://{host}:{port}", file=sys.stderr)
            await self.protocol.run(host=host, port=port)

    async def stop(self):
        """Stop the server."""
        self.protocol.stop()
        await super().stop()

    async def handle_tools_call(self, request_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call method."""
        name = params.get('name')
        arguments = params.get('arguments', {})
        
        if not name:
            return {
                'jsonrpc': '2.0',
                'error': {
                    'code': -32602,
                    'message': "Missing 'name' in params"
                },
                'id': request_id
            }

        # Verifica che lo strumento esista
        tools = await self.list_tools()
        tool = next((t for t in tools if t['name'] == name), None)
        if not tool:
            return {
                'jsonrpc': '2.0',
                'error': {
                    'code': -32601,
                    'message': f"Unknown tool: {name}"
                },
                'id': request_id
            }

        try:
            # Ottieni le credenziali dal config
            auth_details = await self._get_odoo_auth(self.session_manager, self.config, params)
            db = auth_details['db']
            uid = auth_details['uid']
            password = auth_details['password']

            connection = await self.pool.get_connection()
            try:
                handler = connection.connection
                
                # Mapping degli strumenti MCP su chiamate Odoo
                if name == 'odoo_search_read':
                    model = arguments.get('model')
                    domain = arguments.get('domain', [])
                    fields = arguments.get('fields', [])
                    limit = arguments.get('limit', 80)
                    offset = arguments.get('offset', 0)
                    context = arguments.get('context', {})

                    result = handler.execute_kw(
                        model,
                        'search_read',
                        [domain],
                        {
                            'fields': fields,
                            'limit': limit,
                            'offset': offset,
                            'context': context
                        },
                        uid=uid,
                        password=password
                    )
                    mcp_result = {
                        'contents': [
                            {
                                'type': 'text',
                                'text': json.dumps(result, indent=2)
                            }
                        ]
                    }

                elif name == 'odoo_read':
                    model = arguments.get('model')
                    ids = arguments.get('ids', [])
                    fields = arguments.get('fields', [])
                    context = arguments.get('context', {})

                    result = handler.execute_kw(
                        model,
                        'read',
                        [ids],
                        {
                            'fields': fields,
                            'context': context
                        },
                        uid=uid,
                        password=password
                    )
                    mcp_result = {
                        'contents': [
                            {
                                'type': 'text',
                                'text': json.dumps(result, indent=2)
                            }
                        ]
                    }

                elif name == 'odoo_create':
                    model = arguments.get('model')
                    values = arguments.get('values', {})
                    context = arguments.get('context', {})

                    record_id = handler.execute_kw(
                        model,
                        'create',
                        [values],
                        {
                            'context': context
                        },
                        uid=uid,
                        password=password
                    )
                    mcp_result = {
                        'contents': [
                            {
                                'type': 'text',
                                'text': json.dumps({'id': record_id})
                            }
                        ]
                    }

                elif name == 'odoo_write':
                    model = arguments.get('model')
                    ids = arguments.get('ids', [])
                    values = arguments.get('values', {})
                    context = arguments.get('context', {})

                    success = handler.execute_kw(
                        model,
                        'write',
                        [ids, values],
                        {
                            'context': context
                        },
                        uid=uid,
                        password=password
                    )
                    mcp_result = {
                        'contents': [
                            {
                                'type': 'text',
                                'text': json.dumps({'success': success})
                            }
                        ]
                    }

                elif name == 'odoo_unlink':
                    model = arguments.get('model')
                    ids = arguments.get('ids', [])
                    context = arguments.get('context', {})

                    success = handler.execute_kw(
                        model,
                        'unlink',
                        [ids],
                        {
                            'context': context
                        },
                        uid=uid,
                        password=password
                    )
                    mcp_result = {
                        'contents': [
                            {
                                'type': 'text',
                                'text': json.dumps({'success': success})
                            }
                        ]
                    }

                elif name == 'odoo_call_method':
                    model = arguments.get('model')
                    method = arguments.get('method')
                    ids = arguments.get('ids', [])
                    args = arguments.get('args', [])
                    kwargs = arguments.get('kwargs', {})
                    context = arguments.get('context', {})

                    result = handler.execute_kw(
                        model,
                        method,
                        [ids] + args,
                        {
                            'context': context,
                            **kwargs
                        },
                        uid=uid,
                        password=password
                    )
                    # Wrappa il risultato in contents
                    mcp_result = {
                        'contents': [
                            {
                                'type': 'text',
                                'text': json.dumps(result, indent=2)
                            }
                        ]
                    }

                else:
                    return {
                        'jsonrpc': '2.0',
                        'error': {
                            'code': -32601,
                            'message': f"Tool {name} not implemented"
                        },
                        'id': request_id
                    }

                response = {
                    'jsonrpc': '2.0',
                    'result': mcp_result,
                    'id': request_id
                }
                print(f"[DEBUG] MCP response: {response}", file=sys.stderr)
                return response
            finally:
                pass

        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}")
            return {
                'jsonrpc': '2.0',
                'error': {
                    'code': -32603,
                    'message': str(e)
                },
                'id': request_id
            }

    def _handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle incoming requests."""
        try:
            print(f"[DEBUG] MCP request: {json.dumps(request, indent=2)}", file=sys.stderr)
            # Validate request format
            if not isinstance(request, dict):
                raise ValueError("Request must be a JSON object")

            method = request.get('method')
            params = request.get('params', {})
            request_id = request.get('id')
            client_id = request.get('client_id')

            # Handle ping immediately
            if method == 'ping':
                return {
                    'jsonrpc': '2.0',
                    'result': 'pong',
                    'id': request_id
                }

            # Handle other methods
            if method == 'initialize':
                client_info = ClientInfo.from_dict(params)
                server_info = run_async(self.initialize(client_info))
                
                # Ensure capabilities are properly structured
                capabilities = server_info.capabilities
                print(f"[DEBUG] Capabilities before response: {json.dumps(capabilities, indent=2)}", file=sys.stderr)
                
                response = {
                    'jsonrpc': '2.0',
                    'result': {
                        'protocolVersion': PROTOCOL_VERSION,
                        'serverInfo': {
                            'name': server_info.name,
                            'version': server_info.version
                        },
                        'capabilities': capabilities
                    },
                    'id': request_id
                }
                print(f"[DEBUG] MCP initialize response: {json.dumps(response, indent=2)}", file=sys.stderr)
                return response
            elif method == 'get_resource' or method == 'resources/read':
                resource = run_async(self.get_resource(params['uri']))
                response = {
                    'jsonrpc': '2.0',
                    'result': resource,
                    'id': request_id
                }
                print(f"[DEBUG] MCP response: {response}", file=sys.stderr)
                return response
            elif method in ('list_resources', 'resources/list'):
                resources = run_async(self.list_resources())
                response = {
                    'jsonrpc': '2.0',
                    'result': {'resources': resources},
                    'id': request_id
                }
                print(f"[DEBUG] MCP response: {response}", file=sys.stderr)
                return response
            elif method in ('list_tools', 'tools/list'):
                tools = run_async(self.list_tools())
                response = {
                    'jsonrpc': '2.0',
                    'result': {'tools': tools},
                    'id': request_id
                }
                print(f"[DEBUG] MCP response: {response}", file=sys.stderr)
                return response
            elif method in ('list_prompts', 'prompts/list'):
                prompts = run_async(self.list_prompts())
                response = {
                    'jsonrpc': '2.0',
                    'result': {'prompts': prompts},
                    'id': request_id
                }
                print(f"[DEBUG] MCP response: {response}", file=sys.stderr)
                return response
            elif method == 'get_prompt' or method == 'prompts/get':
                name = params.get('name')
                args = params.get('arguments', {})
                result = run_async(self.get_prompt(name, args))
                
                # Converti il risultato nel formato corretto per MCP
                response = {
                    'jsonrpc': '2.0',
                    'result': {
                        'prompt': {
                            'name': name,
                            'arguments': args
                        },
                        'messages': [
                            {
                                'role': 'assistant',
                                'content': {
                                    'type': 'text',
                                    'text': result.message.content.text if result.message and result.message.content else ''
                                }
                            }
                        ],
                        'done': True
                    },
                    'id': request_id
                }
                print(f"[DEBUG] MCP response: {response}", file=sys.stderr)
                return response
            elif method == 'get_server_info':
                server_info = run_async(self.initialize(ClientInfo()))
                response = {
                    'jsonrpc': '2.0',
                    'result': server_info.__dict__,
                    'id': request_id
                }
                print(f"[DEBUG] MCP response: {response}", file=sys.stderr)
                return response
            elif method == 'resources/templates/list':
                templates = [
                    {
                        "uriTemplate": "odoo://{model}/{id}",
                        "name": "Odoo Record",
                        "description": "Represents a single record in an Odoo model",
                        "type": "record",
                        "mimeType": "application/json"
                    },
                    {
                        "uriTemplate": "odoo://{model}/list",
                        "name": "Odoo Record List",
                        "description": "Represents a list of records in an Odoo model",
                        "type": "list",
                        "mimeType": "application/json"
                    },
                    {
                        "uriTemplate": "odoo://{model}/binary/{field}/{id}",
                        "name": "Odoo Binary Field",
                        "description": "Represents a binary field value from an Odoo record",
                        "type": "binary",
                        "mimeType": "application/octet-stream"
                    }
                ]
                response = {
                    'jsonrpc': '2.0',
                    'result': {'resourceTemplates': templates},
                    'id': request_id
                }
                print(f"[DEBUG] MCP response: {response}", file=sys.stderr)
                return response
            elif method in ('notifications/initialized', 'notifications/cancelled'):
                print(f"[DEBUG] Ignored notification: {method}", file=sys.stderr)
                return None
            elif method == 'tools/call':
                return run_async(self.handle_tools_call(request_id, params))
            else:
                raise ProtocolError(f"Unknown method: {method}")

        except Exception as e:
            logger.error(f"Error handling request: {e}")
            error_response = {
                'jsonrpc': '2.0',
                'error': {
                    'code': -32603,
                    'message': str(e)
                },
                'id': request_id
            }
            print(f"[DEBUG] MCP error response: {error_response}", file=sys.stderr)
            return error_response

    async def _handle_list_resource(self, model_name: str, auth_details: Dict[str, Any]) -> Dict[str, Any]:
        """Handle list resource type."""
        db = auth_details["db"]
        uid = auth_details["uid"]
        password = auth_details["password"]
        async with await self.pool.get_connection() as wrapper:
            handler_instance = wrapper.connection
            # Get all records with basic fields
            records = handler_instance.execute_kw(
                db, uid, password,
                model_name, "search_read", [[], ["id", "name"]],
                {"limit": 100}
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

        db = auth_details["db"]
        uid = auth_details["uid"]
        password = auth_details["password"]
        async with await self.pool.get_connection() as wrapper:
            handler_instance = wrapper.connection
            # Read only the binary field
            record_data = handler_instance.execute_kw(
                db, uid, password,
                model_name, "read", [[record_id], [field_name]],
                {}
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

        db = auth_details["db"]
        uid = auth_details["uid"]
        password = auth_details["password"]
        async with await self.pool.get_connection() as wrapper:
            handler_instance = wrapper.connection
            # Read all fields
            record_data = handler_instance.execute_kw(
                db, uid, password,
                model_name, "read", [[record_id]],
                {}
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
        db = config.get('db') or config.get('database')

        if session_id:
            session = session_manager.get_session(session_id)
            if not session:
                raise AuthError(f"Invalid session: {session_id}")
            # Prova a recuperare la password dalla sessione, se disponibile
            session_password = getattr(session, 'password', None) or config.get('api_key') or config.get('password')
            print(f"[DEBUG] _get_odoo_auth: session_id={session_id} user_id={session.user_id} password={session_password} db={db}", file=sys.stderr)
            return {
                "uid": session.user_id,
                "password": session_password,
                "db": db
            }
        elif uid is not None and password is not None:
            print(f"[DEBUG] _get_odoo_auth: explicit uid={uid} password={password} db={db}", file=sys.stderr)
            return {"uid": uid, "password": password, "db": db}
        else:
            # Use default credentials from config
            default_uid = config.get('uid') or 1  # Default to admin user
            default_password = config.get('api_key') or config.get('password')
            if not default_password:
                raise AuthError("No default credentials configured")
            print(f"[DEBUG] _get_odoo_auth: default uid={default_uid} password={default_password} db={db}", file=sys.stderr)
            return {"uid": default_uid, "password": default_password, "db": db}

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

    async def _handle_analyze_record_prompt(self, prompt: dict, args: Dict[str, Any]) -> GetPromptResult:
        """Handle analyze-record prompt."""
        uri = args.get('uri')
        if not uri:
            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text="Please provide a valid URI for the record to analyze (e.g., odoo://res.partner/1)"
                    )
                )
            )
        
        try:
            resource = await self.get_resource(uri)
            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text=f"Analyzing record from {uri}:\n\n{json.dumps(resource['data'], indent=2)}"
                    )
                )
            )
        except Exception as e:
            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text=f"Error analyzing record: {str(e)}"
                    )
                )
            )

    async def _handle_create_record_prompt(self, prompt: dict, args: Dict[str, Any]) -> GetPromptResult:
        """Handle create-record prompt."""
        model = args.get('model')
        if not model:
            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text="Please provide a model name (e.g., res.partner)"
                    )
                )
            )

        try:
            # Get model fields info
            async with await self.pool.get_connection() as wrapper:
                handler = wrapper.connection
                fields_info = handler.execute_kw(model, 'fields_get', [], {'attributes': ['string', 'type', 'required']})
            
            # Format fields info
            fields_text = "Available fields:\n\n"
            for field, info in fields_info.items():
                required = "Required" if info.get('required') else "Optional"
                fields_text += f"- {field} ({info.get('type')}): {info.get('string')} [{required}]\n"

            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text=f"Creating new {model} record.\n\n{fields_text}\n\nUse odoo_create tool with appropriate values to create the record."
                    )
                )
            )
        except Exception as e:
            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text=f"Error getting model information: {str(e)}"
                    )
                )
            )

    async def _handle_update_record_prompt(self, prompt: dict, args: Dict[str, Any]) -> GetPromptResult:
        """Handle update-record prompt."""
        uri = args.get('uri')
        if not uri:
            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text="Please provide a valid URI for the record to update (e.g., odoo://res.partner/1)"
                    )
                )
            )

        try:
            # Get current record data
            resource = await self.get_resource(uri)
            current_data = resource['data']
            
            # Get model and ID from URI
            parts = uri[len("odoo://"):].split('/')
            model, id_str = parts[0], parts[1]
            
            # Get fields info
            async with await self.pool.get_connection() as wrapper:
                handler = wrapper.connection
                fields_info = handler.execute_kw(model, 'fields_get', [], {'attributes': ['string', 'type']})
            
            response = f"Updating {model} record {id_str}.\n\nCurrent values:\n"
            response += json.dumps(current_data, indent=2)
            response += "\n\nAvailable fields:\n"
            for field, info in fields_info.items():
                response += f"- {field} ({info.get('type')}): {info.get('string')}\n"
            
            response += "\nUse odoo_write tool with appropriate values to update the record."

            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text=response
                    )
                )
            )
        except Exception as e:
            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text=f"Error getting record information: {str(e)}"
                    )
                )
            )

    async def _handle_advanced_search_prompt(self, prompt: dict, args: Dict[str, Any]) -> GetPromptResult:
        """Handle advanced-search prompt."""
        model = args.get('model')
        if not model:
            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text="Please provide a model name (e.g., res.partner)"
                    )
                )
            )

        try:
            # Get model fields info
            async with await self.pool.get_connection() as wrapper:
                handler = wrapper.connection
                fields_info = handler.execute_kw(model, 'fields_get', [], {'attributes': ['string', 'type', 'selection']})
            
            # Format domain builder help
            response = f"Building search domain for {model}.\n\nAvailable fields:\n"
            for field, info in fields_info.items():
                field_type = info.get('type')
                if field_type == 'selection':
                    options = [f"'{opt[0]}': {opt[1]}" for opt in info.get('selection', [])]
                    response += f"- {field} ({field_type}): {info.get('string')}\n  Options: {', '.join(options)}\n"
                else:
                    response += f"- {field} ({field_type}): {info.get('string')}\n"
            
            response += "\nDomain format examples:\n"
            response += "- ['name', 'ilike', 'John']  # Name contains 'John'\n"
            response += "- ['create_date', '>', '2023-01-01']  # Created after date\n"
            response += "- ['state', 'in', ['draft', 'done']]  # State is one of values\n"
            response += "- ['|', ('field1', '=', 'x'), ('field2', '=', 'y')]  # OR condition\n"
            response += "\nUse odoo_search_read tool with your domain to search records."

            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text=response
                    )
                )
            )
        except Exception as e:
            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text=f"Error getting model information: {str(e)}"
                    )
                )
            )

    async def _handle_call_method_prompt(self, prompt: dict, args: Dict[str, Any]) -> GetPromptResult:
        """Handle call-method prompt."""
        uri = args.get('uri')
        method = args.get('method')
        
        if not uri:
            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text="Please provide a valid URI (e.g., odoo://res.partner/1)"
                    )
                )
            )
        
        if not method:
            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text="Please provide the method name to call"
                    )
                )
            )

        try:
            # Get model and optional ID from URI
            parts = uri[len("odoo://"):].split('/')
            model = parts[0]
            record_id = int(parts[1]) if len(parts) > 1 else None
            
            response = f"Calling method '{method}' on {model}"
            if record_id:
                response += f" record {record_id}"
            response += ".\n\n"
            
            response += "Use odoo_call_method tool with:\n"
            response += f"- model: '{model}'\n"
            if record_id:
                response += f"- ids: [{record_id}]\n"
            response += f"- method: '{method}'\n"
            response += "- args: []  # Optional positional arguments\n"
            response += "- kwargs: {}  # Optional keyword arguments"

            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text=response
                    )
                )
            )
        except Exception as e:
            return GetPromptResult(
                prompt=prompt,
                message=PromptMessage(
                    content=TextContent(
                        text=f"Error preparing method call: {str(e)}"
                    )
                )
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
