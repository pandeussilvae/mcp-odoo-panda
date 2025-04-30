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
    if not os.path.exists(path):
        # Se il file config.yaml non esiste, prova a usare config.example.yaml
        example_path = "odoo_mcp/config/config.example.yaml"
        if os.path.exists(example_path):
            logger.warning(f"File {path} non trovato. Uso {example_path} come template.")
            with open(example_path, "r") as f:
                config = yaml.safe_load(f)
        else:
            raise FileNotFoundError(f"Nessun file di configurazione trovato in {path} o {example_path}")
    else:
        with open(path, "r") as f:
            config = yaml.safe_load(f)

    # Override con variabili di ambiente
    config["odoo_url"] = os.environ.get("ODOO_URL", config.get("odoo_url"))
    config["database"] = os.environ.get("ODOO_DATABASE", config.get("database"))
    config["username"] = os.environ.get("ODOO_USERNAME", config.get("username"))
    config["api_key"] = os.environ.get("ODOO_PASSWORD", config.get("api_key"))
    config["connection_type"] = os.environ.get("MCP_CONNECTION_TYPE", config.get("connection_type", "stdio"))
    config["transport_type"] = os.environ.get("MCP_TRANSPORT_TYPE", config.get("transport_type", "stdio"))

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

async def sse_endpoint(request: Request):
    """Endpoint SSE per la comunicazione in tempo reale."""
    session_id = request.query_params.get("session_id", str(uuid.uuid4()))
    logger.info(f"Nuova connessione SSE con session_id: {session_id}")
    
    async def event_generator():
        queue = sse_queues[session_id]
        while True:
            if queue:
                msg = queue.popleft()
                yield {"data": json.dumps(msg) + "\n\n"}
            else:
                await asyncio.sleep(10)
                yield {"data": ": ping\n\n"}
    
    return EventSourceResponse(event_generator())

# --- Funzioni di formattazione strumenti/risorse ---
def format_tool(tool):
    return {
        "name": tool.name if hasattr(tool, 'name') else str(tool),
        "description": tool.description if hasattr(tool, 'description') else "",
        "parameters": tool.inputSchema if hasattr(tool, 'inputSchema') else {}
    }

def format_resource(resource):
    if isinstance(resource, types.Resource):
        return {
            "uri": resource.uri,
            "mimeType": resource.mimeType,
            "description": getattr(resource, 'description', "")
        }
    return {
        "uri": resource.get("uri", ""),
        "mimeType": resource.get("mimeType", "application/json"),
        "description": resource.get("description", "")
    }

# --- Endpoint POST /messages ---
async def mcp_messages_endpoint(request: Request):
    """Endpoint per la gestione dei messaggi MCP."""
    data = await request.json()
    session_id = request.query_params.get("session_id")
    
    if not session_id:
        return JSONResponse({"error": "Missing session_id"}, status_code=400)
    
    logger.info(f"Ricevuta richiesta MCP: {data} (session_id={session_id})")
    
    try:
        method = data.get("method")
        req_id = data.get("id")
        
        if method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": await mcp.list_tools(),
                        "resources": RESOURCE_TEMPLATES,
                        "transportTypes": ["stdio", "http", "streamable_http"]
                    },
                    "serverInfo": {
                        "name": "odoo-mcp-server",
                        "version": "0.1.0"
                    }
                }
            }
            return JSONResponse(response)
        elif method == "invokeFunction":
            function_name = data["params"].get("name")
            function_params = data["params"].get("parameters", {})
            result = await mcp.invoke_function(function_name, function_params)
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result
            }
            return JSONResponse(response)
        elif method == 'resources/list':
            # For resources/list, return the resource templates in the correct format
            resources = [
                {
                    "uri": "odoo://{model}/{id}",
                    "type": "record",
                    "data": None,
                    "mime_type": "application/json"
                },
                {
                    "uri": "odoo://{model}/list",
                    "type": "list",
                    "data": None,
                    "mime_type": "application/json"
                },
                {
                    "uri": "odoo://{model}/binary/{field}/{id}",
                    "type": "binary",
                    "data": None,
                    "mime_type": "application/octet-stream"
                }
            ]
            
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "resources": resources
                }
            }
            logger.info(f"Sending resources/list response: {response}")
            return JSONResponse(response)
        elif method == 'resources/templates/list':
            # For resources/templates/list, return our defined templates
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "resourceTemplates": RESOURCE_TEMPLATES
                }
            }
            logger.info(f"Sending resources/templates/list response: {response}")
            return JSONResponse(response)
        else:
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method {method} not found"
                }
            }
            return JSONResponse(response)
    except Exception as e:
        logger.error(f"Errore nella gestione della richiesta: {e}")
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32000,
                "message": str(e)
            }
        }
        return JSONResponse(response)

routes = [
    Route("/sse", endpoint=sse_endpoint),
    Route("/messages", mcp_messages_endpoint, methods=["POST"]),
]

app = Starlette(debug=True, routes=routes)

async def log_registered_tools():
    """Log degli strumenti e risorse registrate"""
    logger.info("Avvio server MCP con strumenti registrati:")
    tools = await mcp.list_tools()
    for tool in tools:
        logger.info(f"- Tool: {tool}")
    resources = await mcp.list_resources()
    for resource in resources:
        logger.info(f"- Resource: {resource}")

def execute_tool(tool_name: str, **kwargs):
    """Esegue uno strumento specifico.
    
    Args:
        tool_name: Nome dello strumento da eseguire
        **kwargs: Parametri per lo strumento
        
    Returns:
        Risultato dell'esecuzione dello strumento
    """
    return tool_manager.execute_tool(tool_name, **kwargs)

def list_tools():
    """Lista tutti gli strumenti disponibili.
    
    Returns:
        Dizionario con tutti gli strumenti e le loro descrizioni
    """
    return tool_manager.list_tools()

def register_tool(name: str, description: str, parameters: dict):
    """Registra un nuovo strumento.
    
    Args:
        name: Nome dello strumento
        description: Descrizione dello strumento
        parameters: Dizionario dei parametri richiesti e le loro descrizioni
    """
    tool_manager.register_tool(name, description, parameters)

if __name__ == "__main__":
    # Determina la modalità di esecuzione
    is_sse = connection_type == "sse" and transport_type == "sse"
    
    if is_sse:
        # Modalità SSE
        import uvicorn
        logger.info("Avvio server MCP in modalità SSE...")
        sse_config = config.get("sse", {})
        uvicorn.run(
            app, 
            host=sse_config.get("host", "0.0.0.0"), 
            port=sse_config.get("port", 8080)
        )
    elif transport_type in ["http", "streamable_http"]:
        # Modalità HTTP
        import uvicorn
        logger.info(f"Avvio server MCP in modalità {transport_type}...")
        http_config = config.get("http", {})
        uvicorn.run(
            app, 
            host=http_config.get("host", "0.0.0.0"), 
            port=http_config.get("port", 8080)
        )
    else:
        # Modalità stdio (default)
        logger.info("Avvio server MCP in modalità stdio...")
        mcp.run() 