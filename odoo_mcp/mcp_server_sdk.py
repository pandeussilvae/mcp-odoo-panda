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

# Crea l'istanza FastMCP
mcp = FastMCP("odoo-mcp-server")

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

# --- RISORSE MCP ---
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

# --- TOOLS MCP ---
class AsyncOdooTools:
    """Classe per gestire gli strumenti Odoo in modo asincrono."""
    
    def __init__(self, odoo_handler):
        self.odoo = odoo_handler
    
    async def list_models(self):
        """Elenca tutti i modelli Odoo disponibili."""
        logger.info("Chiamata a odoo_list_models")
        result = await self.odoo.execute_kw(
            model="ir.model",
            method="search_read",
            args=[[], ["model", "name"]],
            kwargs={}
        )
        return result
    
    async def search_read(self, model, domain, fields, limit=80, offset=0, context=None):
        """Cerca e legge record in un modello Odoo."""
        return await self.odoo.execute_kw(
            model=model,
            method="search_read",
            args=[domain, fields],
            kwargs={"limit": limit, "offset": offset, "context": context or {}}
        )
    
    async def read(self, model, ids, fields, context=None):
        """Legge record specifici da un modello Odoo."""
        return await self.odoo.execute_kw(
            model=model,
            method="read",
            args=[ids, fields],
            kwargs={"context": context or {}}
        )

# Inizializza gli strumenti asincroni
async_tools = AsyncOdooTools(odoo)

@mcp.tool()
def odoo_list_models():
    """Elenca tutti i modelli Odoo disponibili (model e name)."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(async_tools.list_models())

@mcp.tool()
def odoo_search_read(model: str, domain: list, fields: list, *, limit: int = 80, offset: int = 0, context: dict = None):
    """Cerca e legge record in un modello Odoo."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(async_tools.search_read(model, domain, fields, limit, offset, context))

@mcp.tool()
def odoo_read(model: str, ids: list, fields: list, *, context: dict = None):
    """Legge record specifici da un modello Odoo."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(async_tools.read(model, ids, fields, context))

@mcp.tool()
@sync_async
async def odoo_create(model: str, values: dict, *, context: dict = None) -> dict:
    """Crea un nuovo record in un modello Odoo."""
    record_id = await odoo.execute_kw(
        model=model,
        method="create",
        args=[values],
        kwargs={"context": context or {}},
    )
    return {"id": record_id}

@mcp.tool()
@sync_async
async def odoo_write(model: str, ids: list, values: dict, *, context: dict = None) -> dict:
    """Aggiorna record esistenti in un modello Odoo."""
    context = context or {}
    result = await odoo.execute_kw(
        model=model,
        method="write",
        args=[ids, values],
        kwargs={"context": context},
    )
    return {"success": result}

@mcp.tool()
@sync_async
async def odoo_unlink(model: str, ids: list, *, context: dict = None) -> dict:
    """Elimina record da un modello Odoo."""
    result = await odoo.execute_kw(
        model=model,
        method="unlink",
        args=[ids],
        kwargs={"context": context or {}},
    )
    return {"success": result}

@mcp.tool()
@sync_async
async def odoo_call_method(model: str, method: str, *, args: list = None, kwargs: dict = None, context: dict = None) -> dict:
    """Chiama un metodo personalizzato su un modello Odoo."""
    context = context or {}
    result = await odoo.execute_kw(
        model=model,
        method=method,
        args=args or [],
        kwargs={**(kwargs or {}), "context": context},
    )
    return {"result": result}

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
                        "resources": await mcp.list_resources()
                    },
                    "serverInfo": {
                        "name": "odoo-mcp-server",
                        "version": "0.1.0"
                    }
                }
            }
        elif method == "invokeFunction":
            function_name = data["params"].get("name")
            function_params = data["params"].get("parameters", {})
            result = await mcp.invoke_function(function_name, function_params)
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result
            }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method {method} not found"
                }
            }
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
    
    # Invia la risposta attraverso SSE
    sse_queues[session_id].append(response)
    return JSONResponse({"status": "ok"})

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
    is_sse = len(sys.argv) > 1 and sys.argv[1] == "sse"
    
    if is_sse:
        # Modalità SSE
        import uvicorn
        logger.info("Avvio server MCP in modalità SSE...")
        uvicorn.run(app, host="0.0.0.0", port=8080)
    else:
        # Modalità stdio (default)
        logger.info("Avvio server MCP in modalità stdio...")
        mcp.run() 