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
from typing import Dict, Any

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
        with open(example_path, "r") as f:
            config = yaml.safe_load(f)
    else:
        logger.warning(f"File {example_path} non trovato. Uso configurazione di default.")
    
    # 2. Override con config.yaml se esiste
    if os.path.exists(path):
        logger.info(f"Caricamento configurazione da {path}")
        with open(path, "r") as f:
            file_config = yaml.safe_load(f)
            if file_config:
                config.update(file_config)
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

# Definisci i template delle risorse come costanti
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

# Crea l'istanza FastMCP con le capabilities
def create_mcp_instance(transport_types):
    """Create a FastMCP instance with all capabilities."""
    return FastMCP(
        "odoo-mcp-server",
        transport_types=transport_types,
        capabilities={
            "tools": {
                "listChanged": True,
                "tools": TOOLS
            },
            "prompts": {
                "listChanged": True,
                "prompts": PROMPTS
            },
            "resources": {
                "listChanged": True,
                "resources": {template["uriTemplate"]: template for template in RESOURCE_TEMPLATES}
            }
        }
    )

# Initialize MCP instance based on transport type
def initialize_mcp(transport_type):
    """Initialize MCP with appropriate transport types."""
    transport_types = ["stdio"]  # stdio is always available
    
    if transport_type == "streamable_http":
        transport_types.append("streamable_http")
    elif transport_type == "http":
        transport_types.append("http")
    
    mcp = create_mcp_instance(transport_types)
    
    # Register all tools
    @mcp.tool()
    def odoo_login(*, username: str = None, password: str = None, database: str = None, odoo_url: str = None) -> dict:
        """Login to Odoo server."""
        return sync_async(odoo_login)(username=username, password=password, database=database, odoo_url=odoo_url)

    @mcp.tool()
    def odoo_list_models() -> list:
        """List all available Odoo models."""
        return sync_async(odoo_list_models)()

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
    def analyze_record(model: str, id: int) -> str:
        """Analyze an Odoo record and provide insights."""
        return sync_async(analyze_record)(model=model, id=id)

    @mcp.prompt()
    def create_record(model: str, values: dict) -> str:
        """Generate a prompt to create a new Odoo record."""
        return sync_async(create_record)(model=model, values=values)

    @mcp.prompt()
    def update_record(model: str, id: int, values: dict) -> str:
        """Generate a prompt to update an existing Odoo record."""
        return sync_async(update_record)(model=model, id=id, values=values)

    @mcp.prompt()
    def advanced_search(model: str, domain: list) -> str:
        """Generate a prompt for advanced search."""
        return sync_async(advanced_search)(model=model, domain=domain)

    @mcp.prompt()
    def call_method(model: str, method: str, *, args: list = None, kwargs: dict = None) -> str:
        """Generate a prompt for calling a method."""
        return sync_async(call_method)(model=model, method=method, args=args, kwargs=kwargs)

    # Register all resources
    @mcp.resource("odoo://{model}/{id}")
    def get_odoo_record(model: str, id: int):
        """Get a single Odoo record."""
        return sync_async(get_odoo_record)(model=model, id=id)

    @mcp.resource("odoo://{model}/list")
    def list_odoo_records(model: str):
        """Get a list of Odoo records."""
        return sync_async(list_odoo_records)(model=model)

    @mcp.resource("odoo://{model}/binary/{field}/{id}")
    def get_odoo_binary(model: str, field: str, id: int):
        """Get a binary field from an Odoo record."""
        return sync_async(get_odoo_binary)(model=model, field=field, id=id)

    return mcp

# Definisci le routes
routes = [
    Route("/messages", mcp_messages_endpoint, methods=["POST"]),
    Route("/streamable", mcp_messages_endpoint, methods=["POST"]),  # Endpoint per Streamable HTTP
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