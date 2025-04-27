import yaml
import json
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

# --- RISORSE MCP ---
@mcp.resource("odoo://{model}/{id}")
def get_odoo_record(model: str, id: int) -> types.Resource:
    record = odoo.execute_kw(
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
    records = odoo.execute_kw(
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
    data = odoo.execute_kw(
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
def odoo_search_read(model: str, domain: list, fields: list, limit: int = 80, offset: int = 0, context: dict = None) -> list:
    records = odoo.execute_kw(
        model=model,
        method="search_read",
        args=[domain, fields],
        kwargs={"limit": limit, "offset": offset, "context": context or {}},
    )
    return records

@mcp.tool()
def odoo_read(model: str, ids: list, fields: list, context: dict = None) -> list:
    records = odoo.execute_kw(
        model=model,
        method="read",
        args=[ids, fields],
        kwargs={"context": context or {}},
    )
    return records

@mcp.tool()
def odoo_create(model: str, values: dict, context: dict = None) -> dict:
    record_id = odoo.execute_kw(
        model=model,
        method="create",
        args=[values],
        kwargs={"context": context or {}},
    )
    return {"id": record_id}

@mcp.tool()
def odoo_write(model: str, ids: list, values: dict, context: dict = None) -> dict:
    result = odoo.execute_kw(
        model=model,
        method="write",
        args=[ids, values],
        kwargs={"context": context or {}},
    )
    return {"success": result}

@mcp.tool()
def odoo_unlink(model: str, ids: list, context: dict = None) -> dict:
    result = odoo.execute_kw(
        model=model,
        method="unlink",
        args=[ids],
        kwargs={"context": context or {}},
    )
    return {"success": result}

@mcp.tool()
def odoo_call_method(model: str, method: str, args: list = None, kwargs: dict = None, context: dict = None) -> dict:
    result = odoo.execute_kw(
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