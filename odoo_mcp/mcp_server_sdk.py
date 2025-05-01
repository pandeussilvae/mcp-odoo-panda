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
            config.update(file_config)
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

# Crea l'istanza FastMCP
connection_type = config.get("connection_type", "stdio")
transport_type = config.get("transport_type", "stdio")
transport_types = ["stdio"]  # stdio è sempre disponibile

# Gestione SSE
if connection_type == "sse" and transport_type == "sse":
    transport_types.append("sse")
elif transport_type in ["http", "streamable_http"]:
    transport_types.extend(["http", "streamable_http"])

mcp = FastMCP("odoo-mcp-server", transport_types=transport_types)

# Definisci i gestori delle risorse
@mcp.resource("odoo://{model}/{id}")
@sync_async
async def get_odoo_record(model: str, id: int):
    """Ottiene un singolo record Odoo."""
    auth_details = {
        "uid": odoo.global_uid,
        "password": odoo.global_password
    }
    return await resource_manager.get_resource(f"odoo://{model}/{id}", auth_details)

@mcp.resource("odoo://{model}/list")
@sync_async
async def list_odoo_records(model: str):
    """Ottiene una lista di record Odoo."""
    auth_details = {
        "uid": odoo.global_uid,
        "password": odoo.global_password
    }
    return await resource_manager.get_resource(f"odoo://{model}/list", auth_details)

@mcp.resource("odoo://{model}/binary/{field}/{id}")
@sync_async
async def get_odoo_binary(model: str, field: str, id: int):
    """Ottiene un campo binario da un record Odoo."""
    auth_details = {
        "uid": odoo.global_uid,
        "password": odoo.global_password
    }
    return await resource_manager.get_resource(f"odoo://{model}/binary/{field}/{id}", auth_details)

# Sovrascrivi il metodo list_resources di FastMCP
async def list_resources():
    """Lista le risorse disponibili."""
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

mcp.list_resources = list_resources

# --- SESSION MANAGER IN MEMORIA (per estensioni future) ---
sessions = {}

def create_session(username, password, database, odoo_url):
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "username": username,
        "password": password,
        "database": database,
        "odoo_url": odoo_url,
    }
    return session_id

def get_session(session_id):
    return sessions.get(session_id)

# --- TOOL DI LOGIN ---
@mcp.tool()
def odoo_login(*, username: str = None, password: str = None, database: str = None, odoo_url: str = None) -> dict:
    # Gerarchia: runtime > env > config > errore
    try:
        u = get_credential("username", username, config, "ODOO_USERNAME")
        p = get_credential("password", password, config, "ODOO_PASSWORD")
        db = get_credential("database", database, config, "ODOO_DATABASE")
        url = get_credential("odoo_url", odoo_url, config, "ODOO_URL")
    except ValueError as e:
        return {"success": False, "error": str(e)}
    handler = XMLRPCHandler({
        "odoo_url": url,
        "database": db,
        "username": u,
        "api_key": p,
    })
    try:
        uid = handler.common.authenticate(db, u, p, {})
        if not uid:
            return {"success": False, "error": "Invalid credentials"}
        session_id = create_session(u, p, db, url)
        return {"success": True, "session_id": session_id}
    except Exception as e:
        return {"success": False, "error": str(e)}

# --- TOOLS MCP ---
class AsyncOdooTools:
    """Classe per gestire gli strumenti Odoo in modo asincrono."""
    
    def __init__(self, odoo_handler):
        self.odoo = odoo_handler
        self.uid = None
        self.password = None
        if hasattr(odoo_handler, 'global_uid'):
            self.uid = odoo_handler.global_uid
            self.password = odoo_handler.global_password
    
    async def authenticate(self):
        """Autentica l'utente se necessario."""
        if self.uid is None:
            try:
                if isinstance(self.odoo, JSONRPCHandler):
                    # Per JSONRPCHandler, dobbiamo autenticarci usando il metodo call
                    self.uid = await self.odoo.call(
                        service="common",
                        method="login",
                        args=[
                            self.odoo.database,
                            self.odoo.config["username"],
                            self.odoo.config["api_key"]
                        ]
                    )
                    if not self.uid:
                        raise Exception("Autenticazione fallita: credenziali non valide")
                    self.password = self.odoo.config["api_key"]
                    logger.info(f"Autenticazione JSON-RPC riuscita. UID: {self.uid}")
                else:
                    # Per XMLRPCHandler, usa le credenziali globali
                    self.uid = self.odoo.global_uid
                    self.password = self.odoo.global_password
                    logger.info(f"Usando credenziali XML-RPC globali. UID: {self.uid}")
            except Exception as e:
                logger.error(f"Errore durante l'autenticazione: {e}")
                raise
    
    async def list_models(self):
        """Elenca tutti i modelli Odoo disponibili."""
        logger.info("Chiamata a odoo_list_models")
        try:
            await self.authenticate()
            if isinstance(self.odoo, JSONRPCHandler):
                result = await self.odoo.call(
                    service="object",
                    method="execute_kw",
                    args=[
                        self.odoo.database,
                        self.uid,
                        self.password,
                        "ir.model",
                        "search_read",
                        [[]], # domain
                        {"fields": ["model", "name"]} # fields
                    ]
                )
            else:
                result = await self.odoo.execute_kw(
                    model="ir.model",
                    method="search_read",
                    args=[[], ["model", "name"]],
                    kwargs={},
                    uid=self.uid,
                    password=self.password
                )
            return result
        except Exception as e:
            logger.error(f"Errore in list_models: {e}")
            raise
    
    async def search_read(self, model, domain, fields, limit=80, offset=0, context=None):
        """Cerca e legge record in un modello Odoo."""
        try:
            await self.authenticate()
            if isinstance(self.odoo, JSONRPCHandler):
                return await self.odoo.call(
                    service="object",
                    method="execute_kw",
                    args=[
                        self.odoo.database,
                        self.uid,
                        self.password,
                        model,
                        "search_read",
                        [domain, fields],
                        {"limit": limit, "offset": offset, "context": context or {}}
                    ]
                )
            else:
                return await self.odoo.execute_kw(
                    model=model,
                    method="search_read",
                    args=[domain, fields],
                    kwargs={"limit": limit, "offset": offset, "context": context or {}},
                    uid=self.uid,
                    password=self.password
                )
        except Exception as e:
            logger.error(f"Errore in search_read: {e}")
            raise
    
    async def read(self, model, ids, fields, context=None):
        """Legge record specifici da un modello Odoo."""
        try:
            await self.authenticate()
            if isinstance(self.odoo, JSONRPCHandler):
                return await self.odoo.call(
                    service="object",
                    method="execute_kw",
                    args=[
                        self.odoo.database,
                        self.uid,
                        self.password,
                        model,
                        "read",
                        [ids, fields],
                        {"context": context or {}}
                    ]
                )
            else:
                return await self.odoo.execute_kw(
                    model=model,
                    method="read",
                    args=[ids, fields],
                    kwargs={"context": context or {}},
                    uid=self.uid,
                    password=self.password
                )
        except Exception as e:
            logger.error(f"Errore in read: {e}")
            raise

# Inizializza gli strumenti asincroni
async_tools = AsyncOdooTools(odoo)

@mcp.tool()
async def odoo_list_models():
    """Elenca tutti i modelli Odoo disponibili (model e name)."""
    return await async_tools.list_models()

@mcp.tool()
async def odoo_search_read(model: str, domain: list, fields: list, *, limit: int = 80, offset: int = 0, context: dict = {}):
    """Cerca e legge record in un modello Odoo."""
    return await async_tools.search_read(model, domain, fields, limit, offset, context)

@mcp.tool()
async def odoo_read(model: str, ids: list, fields: list, *, context: dict = {}):
    """Legge record specifici da un modello Odoo."""
    return await async_tools.read(model, ids, fields, context)

@mcp.tool()
async def odoo_create(model: str, values: dict, *, context: dict = {}):
    """Crea un nuovo record in un modello Odoo."""
    try:
        record_id = await odoo.execute_kw(
            model=model,
            method="create",
            args=[values],
            kwargs={"context": context}
        )
        return {"id": record_id}
    except Exception as e:
        logger.error(f"Errore in create: {e}")
        raise

@mcp.tool()
async def odoo_write(model: str, ids: list, values: dict, *, context: dict = {}):
    """Aggiorna record esistenti in un modello Odoo."""
    try:
        result = await odoo.execute_kw(
            model=model,
            method="write",
            args=[ids, values],
            kwargs={"context": context}
        )
        return {"success": result}
    except Exception as e:
        logger.error(f"Errore in write: {e}")
        raise

@mcp.tool()
async def odoo_unlink(model: str, ids: list, *, context: dict = {}):
    """Elimina record da un modello Odoo."""
    try:
        result = await odoo.execute_kw(
            model=model,
            method="unlink",
            args=[ids],
            kwargs={"context": context}
        )
        return {"success": result}
    except Exception as e:
        logger.error(f"Errore in unlink: {e}")
        raise

@mcp.tool()
async def odoo_call_method(model: str, method: str, *, args: list = None, kwargs: dict = None, context: dict = {}):
    """Chiama un metodo personalizzato su un modello Odoo."""
    try:
        result = await odoo.execute_kw(
            model=model,
            method=method,
            args=args or [],
            kwargs={**(kwargs or {}), "context": context}
        )
        return {"result": result}
    except Exception as e:
        logger.error(f"Errore in call_method: {e}")
        raise

# --- PROMPTS MCP (esempi base, da personalizzare) ---
@mcp.prompt()
async def analyze_record(model: str, id: int) -> str:
    """Genera un prompt per analizzare un record Odoo."""
    return prompt_manager.get_prompt("analyze_record", {"model": model, "id": str(id)})

@mcp.prompt()
async def create_record(model: str, values: dict) -> str:
    """Genera un prompt per creare un nuovo record Odoo."""
    return prompt_manager.get_prompt("create_record", {"model": model, "values": str(values)})

@mcp.prompt()
async def update_record(model: str, id: int, values: dict) -> str:
    """Genera un prompt per aggiornare un record Odoo."""
    return prompt_manager.get_prompt("update_record", {"model": model, "id": str(id), "values": str(values)})

@mcp.prompt()
def advanced_search(model: str, domain: list) -> str:
    return f"Ricerca avanzata su {model} con dominio {domain}"

@mcp.prompt()
def call_method(model: str, method: str, *, args: list = None, kwargs: dict = None) -> str:
    return f"Chiamata metodo {method} su {model} con args={args} kwargs={kwargs}"

# --- Gestione code SSE per sessione ---
sse_queues = defaultdict(deque)  # session_id -> queue di messaggi

def get_server_capabilities():
    """Ottiene le capabilities del server MCP."""
    # Ottieni i tools registrati come array
    tools_dict = {}
    registered_tools = {
        "odoo_login": odoo_login,
        "odoo_list_models": odoo_list_models,
        "odoo_search_read": odoo_search_read,
        "odoo_read": odoo_read,
        "odoo_create": odoo_create,
        "odoo_write": odoo_write,
        "odoo_unlink": odoo_unlink,
        "odoo_call_method": odoo_call_method
    }
    
    for tool_name, tool_func in registered_tools.items():
        tools_dict[tool_name] = {
            "description": tool_func.__doc__ or "",
            "inputSchema": getattr(tool_func, 'inputSchema', {})
        }
    
    # Ottieni i prompt registrati
    prompts_dict = {
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
        }
    }
    
    # Converti i resource templates in un oggetto con uri come chiavi
    resources_dict = {}
    for template in RESOURCE_TEMPLATES:
        uri = template["uriTemplate"]
        resources_dict[uri] = {
            "uri": uri,
            "uriTemplate": uri,  # Aggiungiamo anche uriTemplate per compatibilità
            "name": template["name"],
            "description": template["description"],
            "type": template["type"],
            "mimeType": template["mimeType"]
        }
    
    return {
        "tools": {
            "listChanged": True,
            "tools": tools_dict
        },
        "prompts": {
            "listChanged": True,
            "prompts": prompts_dict
        },
        "resources": {
            "listChanged": True,
            "resources": resources_dict
        },
        "transportTypes": ["stdio", "http", "streamable_http"],
        "sampling": {},
        "roots": {
            "listChanged": True
        }
    }

def handle_request(request: Dict[str, Any], protocol: str = "stdio") -> Dict[str, Any]:
    """Gestore centralizzato delle richieste per tutti i protocolli."""
    try:
        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            capabilities = get_server_capabilities()
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": capabilities,
                    "serverInfo": {
                        "name": "odoo-mcp-server",
                        "version": "0.1.0"
                    }
                }
            }
        elif method == "prompts/list":
            prompts = get_server_capabilities()["prompts"]["prompts"]
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "prompts": [
                        {
                            "name": name,
                            "description": prompt["description"],
                            "inputSchema": prompt["inputSchema"]
                        }
                        for name, prompt in prompts.items()
                    ]
                }
            }
        elif method == "prompts/get":
            prompt_name = params.get("name")
            if not prompt_name:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": "Invalid params: missing prompt name"
                    }
                }
            
            prompts = get_server_capabilities()["prompts"]["prompts"]
            if prompt_name not in prompts:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Prompt not found: {prompt_name}"
                    }
                }
            
            prompt = prompts[prompt_name]
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "prompt": {
                        "name": prompt_name,
                        "description": prompt["description"],
                        "inputSchema": prompt["inputSchema"]
                    },
                    "contents": [
                        {
                            "role": "assistant",
                            "content": {
                                "type": "text",
                                "text": f"How can I help you with {prompt_name}?"
                            }
                        }
                    ]
                }
            }
        elif method == "resources/list":
            resources = get_server_capabilities()["resources"]["resources"]
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "resources": [
                        {
                            "uri": uri,
                            "uriTemplate": resource["uriTemplate"],
                            "name": resource["name"],
                            "description": resource["description"],
                            "type": resource["type"],
                            "mimeType": resource["mimeType"]
                        }
                        for uri, resource in resources.items()
                    ]
                }
            }
        elif method == "resources/templates/list":
            resources = get_server_capabilities()["resources"]["resources"]
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "resourceTemplates": [
                        {
                            "uri": uri,
                            "uriTemplate": resource["uriTemplate"],
                            "name": resource["name"],
                            "description": resource["description"],
                            "type": resource["type"],
                            "mimeType": resource["mimeType"]
                        }
                        for uri, resource in resources.items()
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
                        "message": "Invalid params: missing uri"
                    }
                }
            
            # Estrai model e id dall'URI
            try:
                # Esempio: odoo://res.partner/1
                parts = uri.split("/")
                if len(parts) != 3:
                    # Se è un template URI, restituisci il template
                    if uri in get_server_capabilities()["resources"]["resources"]:
                        return {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "resource": get_server_capabilities()["resources"]["resources"][uri]
                            }
                        }
                    raise ValueError("Invalid URI format")
                
                model = parts[1]
                id = int(parts[2])
                
                # Usa odoo_read per ottenere i dati
                result = asyncio.run(odoo_read(model, [id], ["name", "id"]))
                if not result:
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32603,
                            "message": f"Resource not found: {uri}"
                        }
                    }
                
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "resource": {
                            "uri": uri,
                            "content": result[0]
                        }
                    }
                }
            except ValueError as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32603,
                        "message": f"Error reading resource: {str(e)}"
                    }
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32603,
                        "message": f"Error reading resource: {str(e)}"
                    }
                }
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            progress_token = params.get("_meta", {}).get("progressToken")
            
            if not tool_name:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": "Invalid params: missing tool name"
                    }
                }
            
            try:
                tools_map = get_server_capabilities()["tools"]
                if tool_name not in tools_map:
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32601,
                            "message": f"Tool not found: {tool_name}"
                        }
                    }
                
                # Esegui il tool
                tool_func = globals()[tool_name]
                if asyncio.iscoroutinefunction(tool_func):
                    loop = asyncio.get_event_loop()
                    result = loop.run_until_complete(tool_func(**arguments))
                else:
                    result = tool_func(**arguments)
                
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
                        "message": f"Error executing tool: {str(e)}"
                    }
                }
        else:
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

def _handle_stdio_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """Handler per richieste stdio."""
    return handle_request(request, "stdio")

async def mcp_messages_endpoint(request: Request):
    """Endpoint per la gestione dei messaggi MCP HTTP/Streamable."""
    data = await request.json()
    session_id = request.query_params.get("session_id")
    
    # Per streamable HTTP, generiamo un session_id se non presente
    if not session_id and request.url.path == "/streamable":
        session_id = str(uuid.uuid4())
        logger.info(f"Generato nuovo session_id per streamable HTTP: {session_id}")
    elif not session_id:
        return JSONResponse({"error": "Missing session_id"}, status_code=400)
    
    logger.info(f"Ricevuta richiesta MCP: {data} (session_id={session_id})")
    
    try:
        response = handle_request(data, "http_streamable")
        return JSONResponse(response)
    except Exception as e:
        logger.error(f"Errore nella gestione della richiesta: {e}")
        response = {
            "jsonrpc": "2.0",
            "id": data.get("id"),
            "error": {
                "code": -32000,
                "message": str(e)
            }
        }
        return JSONResponse(response)

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
    
    # 4. Override con argomenti da linea di comando (massima priorità)
    if args.mode != 'stdio':
        logger.info(f"Override configurazione da argomento da linea di comando: transport_type={args.mode}")
        config['transport_type'] = args.mode
    
    connection_type = config.get("connection_type", "stdio")
    transport_type = config.get("transport_type", "stdio")
    
    logger.info(f"Configurazione finale: connection_type={connection_type}, transport_type={transport_type}")
    
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
        mcp = FastMCP("odoo-mcp-server", transport_types=["stdio"])
        mcp.handle_request = _handle_stdio_request
        mcp.run() 