import yaml
import json
import uuid
from mcp.server.fastmcp import FastMCP
import mcp.types as types
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler

# Carica la configurazione Odoo
def load_odoo_config(path="odoo_mcp/config/config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

config = load_odoo_config()
odoo = XMLRPCHandler(config)
mcp = FastMCP("odoo-mcp-server")

# --- SESSION MANAGER IN MEMORIA ---
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
def odoo_login(username: str, password: str, database: str, odoo_url: str = None) -> dict:
    url = odoo_url or config["odoo_url"]
    handler = XMLRPCHandler({
        "odoo_url": url,
        "database": database,
        "username": username,
        "api_key": password,
    })
    try:
        uid = handler.common.authenticate(database, username, password, {})
        if not uid:
            return {"success": False, "error": "Invalid credentials"}
        session_id = create_session(username, password, database, url)
        return {"success": True, "session_id": session_id}
    except Exception as e:
        return {"success": False, "error": str(e)}

# --- RISORSE MCP ---
@mcp.resource("odoo://{model}/{id}")
def get_odoo_record(model: str, id: int, session_id: str = None) -> types.Resource:
    creds = get_session(session_id) if session_id else None
    handler = odoo
    if creds:
        handler = XMLRPCHandler({
            "odoo_url": creds["odoo_url"],
            "database": creds["database"],
            "username": creds["username"],
            "api_key": creds["password"],
        })
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
def list_odoo_records(model: str, session_id: str = None) -> types.Resource:
    creds = get_session(session_id) if session_id else None
    handler = odoo
    if creds:
        handler = XMLRPCHandler({
            "odoo_url": creds["odoo_url"],
            "database": creds["database"],
            "username": creds["username"],
            "api_key": creds["password"],
        })
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
def get_odoo_binary(model: str, field: str, id: int, session_id: str = None) -> types.Resource:
    creds = get_session(session_id) if session_id else None
    handler = odoo
    if creds:
        handler = XMLRPCHandler({
            "odoo_url": creds["odoo_url"],
            "database": creds["database"],
            "username": creds["username"],
            "api_key": creds["password"],
        })
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
def odoo_search_read(model: str, domain: list, fields: list, limit: int = 80, offset: int = 0, context: dict = None, session_id: str = None) -> list:
    creds = get_session(session_id) if session_id else None
    handler = odoo
    if creds:
        handler = XMLRPCHandler({
            "odoo_url": creds["odoo_url"],
            "database": creds["database"],
            "username": creds["username"],
            "api_key": creds["password"],
        })
    records = handler.execute_kw(
        model=model,
        method="search_read",
        args=[domain, fields],
        kwargs={"limit": limit, "offset": offset, "context": context or {}},
    )
    return records

@mcp.tool()
def odoo_read(model: str, ids: list, fields: list, context: dict = None, session_id: str = None) -> list:
    creds = get_session(session_id) if session_id else None
    handler = odoo
    if creds:
        handler = XMLRPCHandler({
            "odoo_url": creds["odoo_url"],
            "database": creds["database"],
            "username": creds["username"],
            "api_key": creds["password"],
        })
    records = handler.execute_kw(
        model=model,
        method="read",
        args=[ids, fields],
        kwargs={"context": context or {}},
    )
    return records

@mcp.tool()
def odoo_create(model: str, values: dict, context: dict = None, session_id: str = None) -> dict:
    creds = get_session(session_id) if session_id else None
    handler = odoo
    if creds:
        handler = XMLRPCHandler({
            "odoo_url": creds["odoo_url"],
            "database": creds["database"],
            "username": creds["username"],
            "api_key": creds["password"],
        })
    record_id = handler.execute_kw(
        model=model,
        method="create",
        args=[values],
        kwargs={"context": context or {}},
    )
    return {"id": record_id}

@mcp.tool()
def odoo_write(model: str, ids: list, values: dict, context: dict = None, session_id: str = None) -> dict:
    creds = get_session(session_id) if session_id else None
    handler = odoo
    if creds:
        handler = XMLRPCHandler({
            "odoo_url": creds["odoo_url"],
            "database": creds["database"],
            "username": creds["username"],
            "api_key": creds["password"],
        })
    result = handler.execute_kw(
        model=model,
        method="write",
        args=[ids, values],
        kwargs={"context": context or {}},
    )
    return {"success": result}

@mcp.tool()
def odoo_unlink(model: str, ids: list, context: dict = None, session_id: str = None) -> dict:
    creds = get_session(session_id) if session_id else None
    handler = odoo
    if creds:
        handler = XMLRPCHandler({
            "odoo_url": creds["odoo_url"],
            "database": creds["database"],
            "username": creds["username"],
            "api_key": creds["password"],
        })
    result = handler.execute_kw(
        model=model,
        method="unlink",
        args=[ids],
        kwargs={"context": context or {}},
    )
    return {"success": result}

@mcp.tool()
def odoo_call_method(model: str, method: str, args: list = None, kwargs: dict = None, context: dict = None, session_id: str = None) -> dict:
    creds = get_session(session_id) if session_id else None
    handler = odoo
    if creds:
        handler = XMLRPCHandler({
            "odoo_url": creds["odoo_url"],
            "database": creds["database"],
            "username": creds["username"],
            "api_key": creds["password"],
        })
    result = handler.execute_kw(
        model=model,
        method=method,
        args=args or [],
        kwargs=kwargs or {},
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
def call_method(model: str, method: str, args: list = None, kwargs: dict = None) -> str:
    return f"Chiamata metodo {method} su {model} con args={args} kwargs={kwargs}"

if __name__ == "__main__":
    mcp.run() 