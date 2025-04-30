import yaml
import json
import uuid
import os
import sys
import logging
import asyncio
from mcp.server.fastmcp import FastMCP
import mcp.types as types
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.requests import Request
from starlette.routing import Route, Mount

# Configurazione logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    with open(path, "r") as f:
        config = yaml.safe_load(f)
    # Override con variabili di ambiente se presenti
    config["odoo_url"] = os.environ.get("ODOO_URL", config.get("odoo_url"))
    config["database"] = os.environ.get("ODOO_DATABASE", config.get("database"))
    config["username"] = os.environ.get("ODOO_USERNAME", config.get("username"))
    config["api_key"] = os.environ.get("ODOO_PASSWORD", config.get("api_key"))
    return config

config = load_odoo_config()
odoo = XMLRPCHandler(config)
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
def get_odoo_record(model: str, id: int) -> types.Resource:
    handler = odoo
    record = handler.execute_kw(
        model=model,
        method="read",
        args=[[id]],
        kwargs={},
    )
    return types.Resource(
        uri=f"odoo://{model}/{id}",
        mimeType="application/json",
        text=json.dumps(record[0] if record else {})
    )

@mcp.resource("odoo://{model}/list")
def list_odoo_records(model: str) -> types.Resource:
    handler = odoo
    records = handler.execute_kw(
        model=model,
        method="search_read",
        args=[[], ["id", "name"]],
        kwargs={},
    )
    return types.Resource(
        uri=f"odoo://{model}/list",
        mimeType="application/json",
        text=json.dumps(records)
    )

@mcp.resource("odoo://{model}/binary/{field}/{id}")
def get_odoo_binary(model: str, field: str, id: int) -> types.Resource:
    handler = odoo
    data = handler.execute_kw(
        model=model,
        method="read",
        args=[[id], [field]],
        kwargs={},
    )
    binary = data[0][field] if data and field in data[0] else None
    return types.Resource(
        uri=f"odoo://{model}/binary/{field}/{id}",
        mimeType="application/octet-stream",
        text=binary
    )

# --- TOOLS MCP ---
@mcp.tool()
def odoo_search_read(model: str, domain: list, fields: list, *, limit: int = 80, offset: int = 0, context: dict = None) -> list:
    handler = odoo
    context = context or {}
    records = handler.execute_kw(
        model=model,
        method="search_read",
        args=[domain, fields],
        kwargs={"limit": limit, "offset": offset, "context": context},
    )
    return records

@mcp.tool()
def odoo_read(model: str, ids: list, fields: list, *, context: dict = None) -> list:
    handler = odoo
    context = context or {}
    records = handler.execute_kw(
        model=model,
        method="read",
        args=[ids, fields],
        kwargs={"context": context},
    )
    return records

@mcp.tool()
def odoo_create(model: str, values: dict, *, context: dict = None) -> dict:
    handler = odoo
    record_id = handler.execute_kw(
        model=model,
        method="create",
        args=[values],
        kwargs={"context": context or {}},
    )
    return {"id": record_id}

@mcp.tool()
def odoo_write(model: str, ids: list, values: dict, *, context: dict = None) -> dict:
    handler = odoo
    context = context or {}
    result = handler.execute_kw(
        model=model,
        method="write",
        args=[ids, values],
        kwargs={"context": context},
    )
    return {"success": result}

@mcp.tool()
def odoo_unlink(model: str, ids: list, *, context: dict = None) -> dict:
    handler = odoo
    result = handler.execute_kw(
        model=model,
        method="unlink",
        args=[ids],
        kwargs={"context": context or {}},
    )
    return {"success": result}

@mcp.tool()
def odoo_call_method(model: str, method: str, *, args: list = None, kwargs: dict = None, context: dict = None) -> dict:
    handler = odoo
    context = context or {}
    result = handler.execute_kw(
        model=model,
        method=method,
        args=args or [],
        kwargs={**(kwargs or {}), "context": context},
    )
    return {"result": result}

# --- PROMPTS MCP (esempi base, da personalizzare) ---
@mcp.prompt()
def analyze_record(model: str, id: int) -> str:
    return f"Analisi richiesta per {model} con ID {id}"

@mcp.prompt()
def create_record(model: str, values: dict) -> str:
    return f"Creazione richiesta per {model} con valori {values}"

@mcp.prompt()
def update_record(model: str, id: int, values: dict) -> str:
    return f"Aggiornamento richiesto per {model} con ID {id} e valori {values}"

@mcp.prompt()
def advanced_search(model: str, domain: list) -> str:
    return f"Ricerca avanzata su {model} con dominio {domain}"

@mcp.prompt()
def call_method(model: str, method: str, *, args: list = None, kwargs: dict = None) -> str:
    return f"Chiamata metodo {method} su {model} con args={args} kwargs={kwargs}"

@mcp.tool()
def odoo_list_models() -> list:
    """Elenca tutti i modelli Odoo disponibili (model e name)."""
    handler = odoo
    logger.info("Chiamata a odoo_list_models")
    models = handler.execute_kw(
        model="ir.model",
        method="search_read",
        args=[[], ["model", "name"]],
        kwargs={},
    )
    logger.info(f"Trovati {len(models)} modelli")
    return models

def format_tool(tool):
    """Formatta uno strumento nel formato atteso dal client MCP"""
    return {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": tool.get("inputSchema", {})
    }

def format_resource(resource):
    """Formatta una risorsa nel formato atteso dal client MCP"""
    return {
        "uri": resource.get("uri", ""),
        "mimeType": resource.get("mimeType", "application/json"),
        "description": resource.get("description", "")
    }

# Endpoint POST /messages
async def mcp_messages_endpoint(request: Request):
    data = await request.json()
    logger.info(f"Ricevuta richiesta messages: {data}")
    
    # Gestione base del protocollo JSON-RPC
    if not isinstance(data, dict):
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid Request"}, "id": None})
    
    method = data.get("method")
    params = data.get("params", {})
    req_id = data.get("id")
    
    try:
        if method == "initialize":
            # Rispondi con le capabilities del server
            response = {
                "jsonrpc": "2.0",
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": True,
                        "resources": True
                    }
                },
                "id": req_id
            }
        elif method == "getTools":
            # Restituisci la lista degli strumenti disponibili
            tools = await mcp.list_tools()
            formatted_tools = [format_tool(tool) for tool in tools]
            response = {
                "jsonrpc": "2.0",
                "result": {
                    "tools": formatted_tools
                },
                "id": req_id
            }
        elif method == "getResources":
            # Restituisci la lista delle risorse disponibili
            resources = await mcp.list_resources()
            formatted_resources = [format_resource(resource) for resource in resources]
            response = {
                "jsonrpc": "2.0",
                "result": {
                    "resources": formatted_resources
                },
                "id": req_id
            }
        elif method == "invokeFunction":
            # Gestione dell'invocazione di una funzione
            function_name = params.get("name")
            function_params = params.get("parameters", {})
            if hasattr(mcp, "invoke_function"):
                result = await mcp.invoke_function(function_name, function_params)
                response = {
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": req_id
                }
            else:
                response = {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32601,
                        "message": "Method not available"
                    },
                    "id": req_id
                }
        else:
            # Prova a delegare la richiesta a FastMCP se possibile
            if hasattr(mcp, 'handle_jsonrpc'):
                response = await mcp.handle_jsonrpc(data)
            else:
                response = {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32601,
                        "message": f"Method {method} not found"
                    },
                    "id": req_id
                }
    except Exception as e:
        logger.error(f"Errore nella gestione della richiesta: {e}")
        response = {
            "jsonrpc": "2.0",
            "error": {
                "code": -32000,
                "message": str(e)
            },
            "id": req_id
        }
    
    logger.info(f"Risposta: {response}")
    return JSONResponse(response)

routes = [
    Route("/sse", mcp.sse_app(), name='sse'),
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

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "sse":
        import uvicorn
        # Esegui il logging degli strumenti in modo asincrono
        asyncio.run(log_registered_tools())
        uvicorn.run("odoo_mcp.mcp_server_sdk:app", host="0.0.0.0", port=8080, factory=False)
    else:
        mcp.run() 