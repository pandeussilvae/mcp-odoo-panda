"""
Odoo MCP Server SDK implementation.
This module implements the MCP server SDK for Odoo integration.
"""

import yaml
import json
import uuid
import os
import sys
import logging
import asyncio
import time
from collections import defaultdict, deque
from fastmcp import FastMCP
import mcp.types as types
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler
from odoo_mcp.core.jsonrpc_handler import JSONRPCHandler
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.requests import Request
from starlette.routing import Route, Mount
from sse_starlette.sse import EventSourceResponse
from odoo_mcp.prompts.prompt_manager import OdooPromptManager
from odoo_mcp.resources.resource_manager import OdooResourceManager
from odoo_mcp.tools.tool_manager import OdooToolManager
from functools import wraps
import argparse
from typing import Dict, Any, Type, Union, List, Optional, Callable, Set
from odoo_mcp.performance.caching import initialize_cache_manager, cache_manager, CACHE_TYPE
from odoo_mcp.core.protocol_handler import ProtocolHandler
from odoo_mcp.core.capabilities_manager import CapabilitiesManager, ResourceTemplate, Tool, Prompt
from odoo_mcp.core.resource_manager import ResourceManager, Resource
from odoo_mcp.core.connection_pool import ConnectionPool
from odoo_mcp.core.authenticator import OdooAuthenticator
from odoo_mcp.core.session_manager import SessionManager
from odoo_mcp.core.rate_limiter import RateLimiter
from odoo_mcp.core.odoo_bus_handler import OdooBusHandler
from odoo_mcp.error_handling.exceptions import (
    OdooMCPError, ConfigurationError, ProtocolError, AuthError, NetworkError,
    OdooRecordNotFoundError
)

# Configurazione logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sync_async(func):
    """Decoratore per gestire funzioni asincrone in contesti sincroni."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if asyncio.get_event_loop().is_running():
            # Se siamo in un contesto asincrono, esegui normalmente
            return func(*args, **kwargs)
        else:
            # Se siamo in un contesto sincrono, esegui in un nuovo event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(func(*args, **kwargs))
            finally:
                loop.close()
    return wrapper

# Gerarchia di lettura credenziali
# 1. Parametri runtime > 2. Variabili ambiente > 3. File config > 4. Errore

def get_credential(key, runtime_value=None, config=None, env_var=None):
    if runtime_value:
        return runtime_value
    if env_var:
        return os.environ.get(env_var)
    if config and key in config:
        return config[key]
    raise ValueError(f"Missing required credential: {key}. Please provide it at runtime, via env, or in config.")

# Carica la configurazione Odoo
def load_odoo_config(path="odoo_mcp/config/config.yaml"):
    """Carica la configurazione dal file YAML."""
    config = {}
    
    # 1. Carica config.example.yaml come base
    example_path = "odoo_mcp/config/config.example.yaml"
    if os.path.exists(example_path):
        logger.info(f"Caricamento configurazione base da {example_path}")
        with open(example_path, "r", encoding='utf-8') as f:
            config = yaml.safe_load(f)
    else:
        logger.warning(f"File {example_path} non trovato. Uso configurazione di default.")
    
    # 2. Override con config.yaml se esiste
    if os.path.exists(path):
        logger.info(f"Caricamento configurazione da {path}")
        try:
            with open(path, "r", encoding='utf-8') as f:
                file_config = yaml.safe_load(f)
                if file_config:
                    config.update(file_config)
                    logger.info("Configurazione caricata con successo")
                else:
                    logger.warning(f"File {path} è vuoto o non valido")
        except Exception as e:
            logger.error(f"Errore nel caricamento di {path}: {str(e)}")
    else:
        logger.warning(f"File {path} non trovato. Uso configurazione di base.")
    
    # 3. Override con variabili d'ambiente
    env_config = {
        "odoo_url": os.environ.get("ODOO_URL"),
        "database": os.environ.get("ODOO_DATABASE"),
        "username": os.environ.get("ODOO_USERNAME"),
        "api_key": os.environ.get("ODOO_PASSWORD"),
        "connection_type": os.environ.get("MCP_CONNECTION_TYPE"),
        "transport_type": os.environ.get("MCP_TRANSPORT_TYPE")
    }
    
    # Aggiorna solo i valori presenti nelle variabili d'ambiente
    for key, value in env_config.items():
        if value is not None:
            logger.info(f"Override configurazione da variabile d'ambiente: {key}")
            config[key] = value
    
    # Configura il logging
    if "logging" in config:
        log_config = config["logging"]
        logging.basicConfig(
            level=getattr(logging, log_config.get("level", "INFO")),
            format=log_config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
    
    # Log della configurazione finale
    logger.info("Configurazione finale caricata:")
    for key, value in config.items():
        if key != "api_key":  # Non logghiamo le credenziali
            logger.info(f"  {key}: {value}")
    
    return config

def create_odoo_handler(config):
    """Crea l'handler Odoo appropriato in base alla configurazione."""
    protocol = config.get("protocol", "xmlrpc").lower()
    
    if protocol == "jsonrpc":
        logger.info("Inizializzazione JSONRPCHandler...")
        return JSONRPCHandler(config)
    else:
        logger.info("Inizializzazione XMLRPCHandler...")
        return XMLRPCHandler(config)

# Inizializza i gestori
config = load_odoo_config()
odoo = create_odoo_handler(config)
prompt_manager = OdooPromptManager()
resource_manager = OdooResourceManager(odoo)
tool_manager = OdooToolManager(odoo)

# Initialize cache manager with config
initialize_cache_manager(config)

# Definisci i template delle risorse come costanti
RESOURCE_TEMPLATES = [
    {
        "uriTemplate": "odoo://{model}/{id}",
        "name": "Odoo Record",
        "description": "Get a single Odoo record",
        "type": "record",
        "mimeType": "application/json"
    },
    {
        "uriTemplate": "odoo://{model}/list",
        "name": "Odoo Record List",
        "description": "Get a list of Odoo records",
        "type": "list",
        "mimeType": "application/json"
    },
    {
        "uriTemplate": "odoo://{model}/binary/{field}/{id}",
        "name": "Odoo Binary Field",
        "description": "Get a binary field from an Odoo record",
        "type": "binary",
        "mimeType": "application/octet-stream"
    }
]

# Define tools
TOOLS = {
    "odoo_login": {
        "description": "Login to Odoo server",
        "inputSchema": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Username"},
                "password": {"type": "string", "description": "Password"},
                "database": {"type": "string", "description": "Database name"},
                "odoo_url": {"type": "string", "description": "Odoo server URL"}
            }
        }
    },
    "odoo_list_models": {
        "description": "List all available Odoo models",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
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

# Define prompts
PROMPTS = {
    "analyze_record": {
        "description": "Analyze an Odoo record and provide insights",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model name"},
                "id": {"type": "integer", "description": "Record ID"}
            },
            "required": ["model", "id"]
        }
    },
    "create_record": {
        "description": "Generate a prompt to create a new Odoo record",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model name"},
                "values": {"type": "object", "description": "Values for the new record"}
            },
            "required": ["model", "values"]
        }
    },
    "update_record": {
        "description": "Generate a prompt to update an existing Odoo record",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model name"},
                "id": {"type": "integer", "description": "Record ID"},
                "values": {"type": "object", "description": "Values to update"}
            },
            "required": ["model", "id", "values"]
        }
    },
    "advanced_search": {
        "description": "Generate a prompt for advanced search",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model name"},
                "domain": {"type": "array", "description": "Search domain"}
            },
            "required": ["model", "domain"]
        }
    },
    "call_method": {
        "description": "Generate a prompt for calling a method",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model name"},
                "method": {"type": "string", "description": "Method name"},
                "args": {"type": "array", "description": "Method arguments"},
                "kwargs": {"type": "object", "description": "Method keyword arguments"}
            },
            "required": ["model", "method"]
        }
    }
}

# Constants
SERVER_NAME = "odoo-mcp-server"
SERVER_VERSION = "2024.2.5"
PROTOCOL_VERSION = "2024-01-01"

DEFAULT_CAPABILITIES = {
    "tools": {
        "listChanged": True,
        "tools": {
            "odoo_login": {
                "description": "Login to Odoo server",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "username": {"type": "string", "description": "Username"},
                        "password": {"type": "string", "description": "Password"},
                        "database": {"type": "string", "description": "Database name"},
                        "odoo_url": {"type": "string", "description": "Odoo server URL"}
                    }
                }
            }
        }
    },
    "resources": {
        "listChanged": True,
        "resources": RESOURCE_TEMPLATES,
        "subscribe": True
    },
    "streaming": True,
    "sse": True,
    "websocket": True,
    "experimental": {}
}

class OdooMCPServer(FastMCP):
    """Custom MCP Server implementation that ensures proper version and capabilities."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the Odoo MCP Server."""
        # Initialize capabilities before calling parent
        self._capabilities = {
            "tools": {
                "listChanged": True,
                "tools": {}
            },
            "prompts": {
                "listChanged": True,
                "prompts": {}
            },
            "resources": {
                "listChanged": True,
                "resources": {},
                "subscribe": True
            },
            "streaming": True,
            "sse": True,
            "websocket": True,
            "experimental": {}
        }
        
        # Call parent init with our server name
        super().__init__(server_name=SERVER_NAME)
        
        # Store configuration
        self.config = config
        
        # Initialize Odoo handler based on protocol
        protocol = config.get("protocol", "jsonrpc").lower()
        if protocol == "jsonrpc":
            self.odoo = JSONRPCHandler(config)
        else:
            self.odoo = XMLRPCHandler(config)
            
        # Initialize core components
        self.protocol_handler = ProtocolHandler(PROTOCOL_VERSION)
        self.capabilities_manager = CapabilitiesManager()
        self.resource_manager = ResourceManager(
            cache_ttl=config.get('cache_ttl', 300)
        )
        
        # Initialize Odoo components
        self.xmlrpc_pool = ConnectionPool(config, XMLRPCHandler)
        self.jsonrpc_pool = ConnectionPool(config, JSONRPCHandler)
        self.authenticator = OdooAuthenticator(config, self.xmlrpc_pool)
        self.session_manager = SessionManager(config, self.authenticator, self.xmlrpc_pool)
        self.rate_limiter = RateLimiter(
            requests_per_minute=config.get('requests_per_minute', 120),
            max_wait_seconds=config.get('rate_limit_max_wait_seconds', None)
        )
        
        # Initialize bus handler
        self.bus_handler = OdooBusHandler(config, self._notify_resource_update)
        
        # Register resource handlers
        self._register_resource_handlers()
        
        # Register tools and prompts
        self._register_tools_and_prompts()
        
        # Auto-authenticate if credentials are available
        self._auto_authenticate()

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

    async def _auto_authenticate(self):
        """Automatically authenticate using config credentials."""
        try:
            username = self.config.get("username")
            password = self.config.get("password")
            database = self.config.get("database")
            odoo_url = self.config.get("odoo_url")
            
            if not all([username, password, database, odoo_url]):
                missing = []
                if not username: missing.append("username")
                if not password: missing.append("password")
                if not database: missing.append("database")
                if not odoo_url: missing.append("odoo_url")
                logger.warning(f"Missing credentials in config for auto-authentication: {', '.join(missing)}")
                return
                
            logger.info(f"Auto-authenticating with Odoo: {odoo_url}, database: {database}, user: {username}")
            uid = await self.odoo.authenticate(database, username, password)
            
            if uid:
                self.odoo.global_uid = uid
                self.odoo.global_password = password
                logger.info("Auto-authentication successful")
            else:
                logger.error("Auto-authentication failed")
        except Exception as e:
            logger.error(f"Error during auto-authentication: {str(e)}")

    @property
    def version(self) -> str:
        return SERVER_VERSION

    @property
    def name(self) -> str:
        return SERVER_NAME

    @property
    def capabilities(self):
        return self.capabilities_manager.get_capabilities()

    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP requests."""
        try:
            method = request.get("method")
            req_id = request.get("id")
            params = request.get("params", {})

            if method == "initialize":
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "serverInfo": {
                            "name": SERVER_NAME,
                            "version": SERVER_VERSION
                        },
                        "capabilities": self.capabilities
                    }
                }

            # Check authentication for all methods except initialize and odoo_login
            if method not in ["initialize", "tools/call"] or (method == "tools/call" and params.get("name") != "odoo_login"):
                if not hasattr(self.odoo, 'global_uid') or not hasattr(self.odoo, 'global_password'):
                    # Try auto-authentication if not already authenticated
                    await self._auto_authenticate()
                    
                    # If still not authenticated, return error
                    if not hasattr(self.odoo, 'global_uid') or not hasattr(self.odoo, 'global_password'):
                        return {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {
                                "code": -32000,
                                "message": "Authentication required. Please call odoo_login first."
                            }
                        }

            return await super().handle_request(request)

        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }

    # FastMCP Decorators for Tools
    @mcp.tool()
    async def odoo_login(self, database: str, username: str, password: str) -> Dict[str, Any]:
        """Authenticate with Odoo."""
        try:
            uid = await self.odoo.authenticate(database, username, password)
            if uid:
                self.odoo.global_uid = uid
                self.odoo.global_password = password
                return {
                    "uid": uid,
                    "session_id": str(uuid.uuid4())
                }
            else:
                raise AuthError("Authentication failed")
        except Exception as e:
            raise AuthError(f"Authentication error: {str(e)}")

    @mcp.tool()
    async def odoo_list_models(self) -> List[Dict[str, Any]]:
        """List all available Odoo models."""
        try:
            models = await self.xmlrpc_pool.execute_kw(
                model="ir.model",
                method="search_read",
                args=[],
                kwargs={"fields": ["model", "name"]}
            )
            return models
        except Exception as e:
            raise ProtocolError(f"Error listing models: {str(e)}")

    @mcp.tool()
    async def odoo_search_read(self, model: str, domain: List[Any], fields: List[str]) -> List[Dict[str, Any]]:
        """Search and read records from an Odoo model."""
        try:
            records = await self.jsonrpc_pool.execute_kw(
                model=model,
                method="search_read",
                args=[domain],
                kwargs={}
            )
            return records
        except Exception as e:
            raise ProtocolError(f"Error searching records: {str(e)}")

    @mcp.tool()
    async def odoo_read(self, model: str, ids: List[int], fields: List[str]) -> List[Dict[str, Any]]:
        """Read specific records from an Odoo model."""
        try:
            records = await self.jsonrpc_pool.execute_kw(
                model=model,
                method="read",
                args=[ids],
                kwargs={"fields": fields}
            )
            return records
        except Exception as e:
            raise ProtocolError(f"Error reading records: {str(e)}")

    @mcp.tool()
    async def odoo_create(self, model: str, values: Dict[str, Any]) -> int:
        """Create a new record in an Odoo model."""
        try:
            record_id = await self.jsonrpc_pool.execute_kw(
                model=model,
                method="create",
                args=[values]
            )
            return record_id
        except Exception as e:
            raise ProtocolError(f"Error creating record: {str(e)}")

    @mcp.tool()
    async def odoo_write(self, model: str, ids: List[int], values: Dict[str, Any]) -> bool:
        """Update existing records in an Odoo model."""
        try:
            result = await self.jsonrpc_pool.execute_kw(
                model=model,
                method="write",
                args=[ids, values]
            )
            return result
        except Exception as e:
            raise ProtocolError(f"Error updating records: {str(e)}")

    @mcp.tool()
    async def odoo_unlink(self, model: str, ids: List[int]) -> bool:
        """Delete records from an Odoo model."""
        try:
            result = await self.pool.execute_kw(
                model=model,
                method="unlink",
                args=[ids],
                kwargs={}
            )
            return result
        except Exception as e:
            raise ProtocolError(f"Error deleting records: {str(e)}")

    # FastMCP Decorators for Resources
    @mcp.resource("odoo://{model}/{id}")
    async def get_odoo_record(self, model: str, id: int) -> Resource:
        """Get a single Odoo record."""
        return await self._handle_odoo_record(f"odoo://{model}/{id}")

    @mcp.resource("odoo://{model}/list")
    async def get_odoo_record_list(self, model: str) -> Resource:
        """Get a list of Odoo records."""
        return await self._handle_odoo_record_list(f"odoo://{model}/list")

    @mcp.resource("odoo://{model}/binary/{field}/{id}")
    async def get_odoo_binary_field(self, model: str, field: str, id: int) -> Resource:
        """Get a binary field from an Odoo record."""
        return await self._handle_odoo_binary_field(f"odoo://{model}/binary/{field}/{id}")

    # FastMCP Decorators for Prompts
    @mcp.prompt()
    async def analyze_record(self, model: str, id: int) -> Dict[str, Any]:
        """Analyze an Odoo record and provide insights."""
        try:
            # Get record details
            record = await self.pool.execute_kw(
                model=model,
                method="read",
                args=[[id]],
                kwargs={}
            )
            
            if not record:
                raise OdooRecordNotFoundError(f"Record {id} not found in model {model}")
            
            # Get field information
            fields_info = await self.pool.execute_kw(
                model=model,
                method="fields_get",
                args=[],
                kwargs={}
            )
            
            return {
                "record": record[0],
                "fields_info": fields_info,
                "analysis": {
                    "model": model,
                    "id": id,
                    "fields_count": len(fields_info),
                    "required_fields": [f for f, info in fields_info.items() if info.get("required")],
                    "computed_fields": [f for f, info in fields_info.items() if info.get("compute")],
                    "related_fields": [f for f, info in fields_info.items() if info.get("related")]
                }
            }
        except Exception as e:
            raise ProtocolError(f"Error analyzing record: {str(e)}")

    @mcp.prompt()
    async def create_record(self, model: str, values: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new record in an Odoo model."""
        try:
            # Get field information
            fields_info = await self.pool.execute_kw(
                model=model,
                method="fields_get",
                args=[],
                kwargs={}
            )
            
            # Validate required fields
            required_fields = [f for f, info in fields_info.items() if info.get("required")]
            missing_fields = [f for f in required_fields if f not in values]
            
            if missing_fields:
                raise ProtocolError(f"Missing required fields: {', '.join(missing_fields)}")
            
            # Create record
            record_id = await self.pool.execute_kw(
                model=model,
                method="create",
                args=[values],
                kwargs={}
            )
            
            return {
                "record_id": record_id,
                "fields_info": fields_info,
                "values": values
            }
        except Exception as e:
            raise ProtocolError(f"Error creating record: {str(e)}")

    @mcp.prompt()
    async def update_record(self, model: str, id: int, values: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing record in an Odoo model."""
        try:
            # Get current record
            record = await self.pool.execute_kw(
                model=model,
                method="read",
                args=[[id]],
                kwargs={}
            )
            
            if not record:
                raise OdooRecordNotFoundError(f"Record {id} not found in model {model}")
            
            # Get field information
            fields_info = await self.pool.execute_kw(
                model=model,
                method="fields_get",
                args=[],
                kwargs={}
            )
            
            # Update record
            result = await self.pool.execute_kw(
                model=model,
                method="write",
                args=[[id], values],
                kwargs={}
            )
            
            return {
                "success": result,
                "record": record[0],
                "fields_info": fields_info,
                "values": values
            }
        except Exception as e:
            raise ProtocolError(f"Error updating record: {str(e)}")

    @mcp.prompt()
    async def advanced_search(self, model: str, domain: List[Any]) -> Dict[str, Any]:
        """Perform an advanced search on an Odoo model."""
        try:
            # Get field information
            fields_info = await self.pool.execute_kw(
                model=model,
                method="fields_get",
                args=[],
                kwargs={}
            )
            
            # Search records
            records = await self.pool.execute_kw(
                model=model,
                method="search_read",
                args=[domain],
                kwargs={}
            )
            
            return {
                "records": records,
                "fields_info": fields_info,
                "domain": domain,
                "count": len(records)
            }
        except Exception as e:
            raise ProtocolError(f"Error performing advanced search: {str(e)}")

    @mcp.prompt()
    async def call_method(self, model: str, method: str, args: List[Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Call a method on an Odoo model."""
        try:
            # Get method information
            methods_info = await self.pool.execute_kw(
                model=model,
                method="fields_get",
                args=[],
                kwargs={"attributes": ["method"]}
            )
            
            # Call method
            result = await self.pool.execute_kw(
                model=model,
                method=method,
                args=args,
                kwargs=kwargs
            )
            
            return {
                "result": result,
                "methods_info": methods_info,
                "method": method,
                "args": args,
                "kwargs": kwargs
            }
        except Exception as e:
            raise ProtocolError(f"Error calling method: {str(e)}")

    # Resource Handlers
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

def create_mcp_instance(transport_types):
    """Create a FastMCP instance with all capabilities."""
    if isinstance(transport_types, str):
        transport_types = [transport_types]
    return OdooMCPServer(transport_types)

def parse_odoo_uri(uri: str) -> tuple:
    """Parse an Odoo URI into its components."""
    if not uri.startswith("odoo://"):
        raise ValueError("Invalid URI scheme - must start with odoo://")
    
    # Remove the scheme
    path = uri[7:]  # len("odoo://") == 7
    parts = path.split("/")
    
    if len(parts) < 2:
        raise ValueError("Invalid URI format - must contain at least model")
    
    model = parts[0]
    
    if len(parts) == 2:
        if parts[1] == "list":
            return model, "list", None
        try:
            id = int(parts[1])
            return model, "record", id
        except ValueError:
            if parts[1] == "list":
                return model, "list", None
            raise ValueError("Invalid record ID")
    
    if len(parts) == 4 and parts[1] == "binary":
        return model, "binary", {"field": parts[2], "id": int(parts[3])}
    
    raise ValueError("Invalid URI format")

# Initialize MCP instance based on transport type
def initialize_mcp(transport_type):
    """Initialize MCP with appropriate transport types."""
    transport_types = ["stdio"]  # stdio is always available
    
    if transport_type == "streamable_http":
        transport_types.append("streamable_http")
    elif transport_type == "http":
        transport_types.append("http")
    
    logger.info(f"Initializing MCP server with transport types: {transport_types}")
    mcp = create_mcp_instance(transport_types)

    # Register request handler
    async def handle_request(request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP requests."""
        try:
            method = request.get("method")
            req_id = request.get("id")
            params = request.get("params", {})

            if method == "initialize":
                client_info = ClientInfo.from_dict(params)
                server_info = run_async(mcp.initialize(client_info))
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-01-01",
                        "capabilities": server_info.capabilities,
                        "serverInfo": {
                            "name": SERVER_NAME,
                            "version": SERVER_VERSION
                        }
                    }
                }

            # Get authentication info
            try:
                uid = getattr(odoo, 'global_uid', None)
                password = getattr(odoo, 'global_password', None)
                if not uid or not password:
                    # Try to authenticate with default credentials
                    username = get_credential("username", None, config, "ODOO_USERNAME")
                    password = get_credential("password", None, config, "ODOO_PASSWORD")
                    database = get_credential("database", None, config, "ODOO_DATABASE")
                    uid = await odoo.authenticate(database, username, password)
                    if not uid:
                        return {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {
                                "code": -32000,
                                "message": "Authentication required. Please call odoo_login first."
                            }
                        }
                    odoo.global_uid = uid
                    odoo.global_password = password
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32000,
                        "message": f"Authentication error: {str(e)}"
                    }
                }

            if method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                progress_token = params.get("_meta", {}).get("progressToken")

                if tool_name not in TOOLS:
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32601,
                            "message": f"Tool not found: {tool_name}"
                        }
                    }

                try:
                    if tool_name == "odoo_list_models":
                        result = await odoo.execute_kw(
                            model="ir.model",
                            method="search_read",
                            args=[[], ["model", "name"]],
                            kwargs={},
                            uid=uid,
                            password=password
                        )
                    else:
                        # Get the tool function from the global namespace
                        tool_func = globals()[tool_name]
                        result = await tool_func(**arguments) if asyncio.iscoroutinefunction(tool_func) else tool_func(**arguments)
                    
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "value": result,
                            "_meta": {
                                "progressToken": progress_token
                            }
                        }
                    }
                except Exception as e:
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32000,
                            "message": f"Error executing tool {tool_name}: {str(e)}"
                        }
                    }

            elif method == "resources/list":
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "resources": [
                            {
                                "uri": template["uriTemplate"],
                                "uriTemplate": template["uriTemplate"],
                                "name": template["name"],
                                "description": template["description"],
                                "type": template["type"],
                                "mimeType": template["mimeType"]
                            }
                            for template in RESOURCE_TEMPLATES
                        ]
                    }
                }

            elif method == "resources/templates/list":
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "resourceTemplates": [
                            {
                                "uri": template["uriTemplate"],
                                "uriTemplate": template["uriTemplate"],
                                "name": template["name"],
                                "description": template["description"],
                                "type": template["type"],
                                "mimeType": template["mimeType"]
                            }
                            for template in RESOURCE_TEMPLATES
                        ]
                    }
                }

            elif method == "resources/read":
                uri = params.get("uri")
                if not uri:
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32602,
                            "message": "Missing uri parameter"
                        }
                    }

                try:
                    model, type, id_or_info = parse_odoo_uri(uri)
                    
                    if type == "list":
                        result = await list_odoo_records(model)
                    elif type == "record":
                        result = await get_odoo_record(model, id_or_info)
                    else:  # binary
                        result = await get_odoo_binary(model, id_or_info["field"], id_or_info["id"])

                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "resource": {
                                "uri": uri,
                                "type": type,
                                "mimeType": "application/json"
                            },
                            "contents": [
                                {
                                    "uri": uri,
                                    "type": "text",
                                    "text": json.dumps(result, indent=2)
                                }
                            ]
                        }
                    }
                except Exception as e:
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32000,
                            "message": f"Error reading resource: {str(e)}"
                        }
                    }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method {method} not found"
                }
            }

        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32000,
                    "message": str(e)
                }
            }

    mcp.handle_request = handle_request
    
    # Register all tools
    @mcp.tool()
    async def odoo_login(*, username: str = None, password: str = None, database: str = None, odoo_url: str = None) -> dict:
        """Login to Odoo server."""
        try:
            u = get_credential("username", username, config, "ODOO_USERNAME")
            p = get_credential("password", password, config, "ODOO_PASSWORD")
            db = get_credential("database", database, config, "ODOO_DATABASE")
            url = get_credential("odoo_url", odoo_url, config, "ODOO_URL")
        except ValueError as e:
            return {"success": False, "error": str(e)}

        try:
            uid = await odoo.authenticate(db, u, p)
            if not uid:
                return {"success": False, "error": "Invalid credentials"}
            odoo.global_uid = uid
            odoo.global_password = p
            return {"success": True, "uid": uid}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def odoo_list_models() -> list:
        """List all available Odoo models."""
        if not hasattr(odoo, 'global_uid') or not hasattr(odoo, 'global_password'):
            raise Exception("Authentication required. Please call odoo_login first.")
        
        return await odoo.execute_kw(
            model="ir.model",
            method="search_read",
            args=[[], ["model", "name"]],
            kwargs={},
            uid=odoo.global_uid,
            password=odoo.global_password
        )

    @mcp.tool()
    def odoo_search_read(model: str, domain: list, fields: list, *, limit: int = 80, offset: int = 0, context: dict = {}) -> list:
        """Search and read records from an Odoo model."""
        return sync_async(odoo_search_read)(model=model, domain=domain, fields=fields, limit=limit, offset=offset, context=context)

    @mcp.tool()
    def odoo_read(model: str, ids: list, fields: list, *, context: dict = {}) -> list:
        """Read specific records from an Odoo model."""
        return sync_async(odoo_read)(model=model, ids=ids, fields=fields, context=context)

    @mcp.tool()
    def odoo_create(model: str, values: dict, *, context: dict = {}) -> dict:
        """Create a new record in an Odoo model."""
        return sync_async(odoo_create)(model=model, values=values, context=context)

    @mcp.tool()
    def odoo_write(model: str, ids: list, values: dict, *, context: dict = {}) -> dict:
        """Update existing records in an Odoo model."""
        return sync_async(odoo_write)(model=model, ids=ids, values=values, context=context)

    @mcp.tool()
    def odoo_unlink(model: str, ids: list, *, context: dict = {}) -> dict:
        """Delete records from an Odoo model."""
        return sync_async(odoo_unlink)(model=model, ids=ids, context=context)

    @mcp.tool()
    def odoo_call_method(model: str, method: str, *, args: list = None, kwargs: dict = None, context: dict = {}) -> dict:
        """Call a custom method on an Odoo model."""
        return sync_async(odoo_call_method)(model=model, method=method, args=args, kwargs=kwargs, context=context)

    # Register all prompts
    @mcp.prompt()
    async def analyze_record(model: str, id: int) -> str:
        """Analyze an Odoo record and provide insights."""
        if not hasattr(odoo, 'global_uid') or not hasattr(odoo, 'global_password'):
            raise Exception("Authentication required. Please call odoo_login first.")
        
        record = await odoo.execute_kw(
            model=model,
            method="read",
            args=[[id]],
            kwargs={},
            uid=odoo.global_uid,
            password=odoo.global_password
        )
        if not record:
            return f"Record {id} not found in model {model}"
        return f"Analysis of {model} record {id}:\n{json.dumps(record[0], indent=2)}"

    @mcp.prompt()
    async def create_record(model: str, values: dict) -> str:
        """Generate a prompt to create a new Odoo record."""
        if not hasattr(odoo, 'global_uid') or not hasattr(odoo, 'global_password'):
            raise Exception("Authentication required. Please call odoo_login first.")
        
        fields_info = await odoo.execute_kw(
            model=model,
            method="fields_get",
            args=[],
            kwargs={},
            uid=odoo.global_uid,
            password=odoo.global_password
        )
        return f"Creating new {model} record with values:\n{json.dumps(values, indent=2)}\n\nAvailable fields:\n{json.dumps(fields_info, indent=2)}"

    @mcp.prompt()
    async def update_record(model: str, id: int, values: dict) -> str:
        """Generate a prompt to update an existing Odoo record."""
        if not hasattr(odoo, 'global_uid') or not hasattr(odoo, 'global_password'):
            raise Exception("Authentication required. Please call odoo_login first.")
        
        record = await odoo.execute_kw(
            model=model,
            method="read",
            args=[[id]],
            kwargs={},
            uid=odoo.global_uid,
            password=odoo.global_password
        )
        if not record:
            return f"Record {id} not found in model {model}"
        return f"Updating {model} record {id}:\nCurrent values:\n{json.dumps(record[0], indent=2)}\n\nNew values:\n{json.dumps(values, indent=2)}"

    @mcp.prompt()
    async def advanced_search(model: str, domain: list) -> str:
        """Generate a prompt for advanced search."""
        if not hasattr(odoo, 'global_uid') or not hasattr(odoo, 'global_password'):
            raise Exception("Authentication required. Please call odoo_login first.")
        
        fields_info = await odoo.execute_kw(
            model=model,
            method="fields_get",
            args=[],
            kwargs={},
            uid=odoo.global_uid,
            password=odoo.global_password
        )
        return f"Advanced search in {model} with domain:\n{json.dumps(domain, indent=2)}\n\nAvailable fields:\n{json.dumps(fields_info, indent=2)}"

    @mcp.prompt()
    async def call_method(model: str, method: str, *, args: list = None, kwargs: dict = None) -> str:
        """Generate a prompt for calling a method."""
        if not hasattr(odoo, 'global_uid') or not hasattr(odoo, 'global_password'):
            raise Exception("Authentication required. Please call odoo_login first.")
        
        methods = await odoo.execute_kw(
            model=model,
            method="fields_get",
            args=[],
            kwargs={"attributes": ["method"]},
            uid=odoo.global_uid,
            password=odoo.global_password
        )
        return f"Calling method {method} on {model} with:\nargs: {json.dumps(args or [], indent=2)}\nkwargs: {json.dumps(kwargs or {}, indent=2)}\n\nAvailable methods:\n{json.dumps(methods, indent=2)}"

    # Register all resources
    @mcp.resource("odoo://{model}/{id}")
    async def get_odoo_record(model: str, id: int):
        """Get a single Odoo record."""
        if not hasattr(odoo, 'global_uid') or not hasattr(odoo, 'global_password'):
            raise Exception("Authentication required. Please call odoo_login first.")
        
        record = await odoo.execute_kw(
            model=model,
            method="read",
            args=[[id]],
            kwargs={},
            uid=odoo.global_uid,
            password=odoo.global_password
        )
        return record[0] if record else None

    @mcp.resource("odoo://{model}/list")
    async def list_odoo_records(model: str):
        """Get a list of Odoo records."""
        if not hasattr(odoo, 'global_uid') or not hasattr(odoo, 'global_password'):
            raise Exception("Authentication required. Please call odoo_login first.")
        
        return await odoo.execute_kw(
            model=model,
            method="search_read",
            args=[[], ["name", "id"]],
            kwargs={"limit": 50},
            uid=odoo.global_uid,
            password=odoo.global_password
        )

    @mcp.resource("odoo://{model}/binary/{field}/{id}")
    async def get_odoo_binary(model: str, field: str, id: int):
        """Get a binary field from an Odoo record."""
        if not hasattr(odoo, 'global_uid') or not hasattr(odoo, 'global_password'):
            raise Exception("Authentication required. Please call odoo_login first.")
        
        record = await odoo.execute_kw(
            model=model,
            method="read",
            args=[[id], [field]],
            kwargs={},
            uid=odoo.global_uid,
            password=odoo.global_password
        )
        return record[0][field] if record else None

    return mcp

# HTTP endpoint handler
async def mcp_messages_endpoint(request: Request):
    """Handle MCP messages for HTTP/Streamable endpoints."""
    try:
        data = await request.json()
        session_id = request.query_params.get("session_id")
        
        # For streamable HTTP, generate a session_id if not present
        if not session_id and request.url.path == "/streamable":
            session_id = str(uuid.uuid4())
            logger.info(f"Generated new session_id for streamable HTTP: {session_id}")
        elif not session_id:
            return JSONResponse({"error": "Missing session_id"}, status_code=400)
        
        logger.info(f"Received MCP request: {data} (session_id={session_id})")
        
        # Handle the request using the MCP instance
        response = await mcp.handle_request(data)
        return JSONResponse(response)
    except Exception as e:
        logger.error(f"Error handling request: {e}")
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": data.get("id"),
            "error": {
                "code": -32000,
                "message": str(e)
            }
        })

# Define routes
routes = [
    Route("/messages", mcp_messages_endpoint, methods=["POST"]),
    Route("/streamable", mcp_messages_endpoint, methods=["POST"]),  # Endpoint for Streamable HTTP
]

app = Starlette(debug=True, routes=routes)

if __name__ == "__main__":
    # Determina la modalità di esecuzione
    parser = argparse.ArgumentParser(description='MCP Server for Odoo')
    parser.add_argument('mode', nargs='?', default='stdio',
                      choices=['stdio', 'http', 'streamable_http'],
                      help='Server mode (stdio, http, or streamable_http)')
    args = parser.parse_args()
    
    # Carica la configurazione
    config = load_odoo_config()
    
    # Override con argomenti da linea di comando (massima priorità)
    if args.mode != 'stdio':
        logger.info(f"Override configurazione da argomento da linea di comando: transport_type={args.mode}")
        config['transport_type'] = args.mode
    
    connection_type = config.get("connection_type", "stdio")
    transport_type = config.get("transport_type", "stdio")
    
    logger.info(f"Configurazione finale: connection_type={connection_type}, transport_type={transport_type}")
    
    # Initialize MCP instance
    mcp = initialize_mcp(transport_type)
    
    if transport_type in ["http", "streamable_http"]:
        # Modalità HTTP
        import uvicorn
        logger.info(f"Avvio server MCP in modalità {transport_type}...")
        http_config = config.get("http", {})
        host = http_config.get("host", "0.0.0.0")
        port = http_config.get("port", 8080)
        logger.info(f"Server in ascolto su http://{host}:{port}")
        if transport_type == "streamable_http":
            logger.info("Streamable HTTP disponibile su http://{host}:{port}/streamable")
        uvicorn.run(
            app, 
            host=host,
            port=port
        )
    else:
        # Modalità stdio (default)
        logger.info("Avvio server MCP in modalità stdio...")
        mcp.run() 