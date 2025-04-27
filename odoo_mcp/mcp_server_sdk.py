import asyncio
import yaml
import json
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler

# Carica la configurazione Odoo
def load_odoo_config(path="odoo_mcp/config/config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

config = load_odoo_config()
odoo = XMLRPCHandler(config)  # Istanza handler Odoo

server = Server("odoo-mcp-server")

# Esempio: risorsa Odoo MCP standard
@server.resource("odoo://{model}/{id}")
async def get_odoo_record(model: str, id: int) -> types.Resource:
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

# Esempio: tool Odoo MCP standard
@server.tool()
async def odoo_search_read(model: str, domain: list, fields: list) -> list:
    records = odoo.execute_kw(
        model=model,
        method="search_read",
        args=[domain, fields],
        kwargs={},
    )
    return records

async def run():
    async with stdio_server() as (read, write):
        await server.run(read, write)

if __name__ == "__main__":
    asyncio.run(run()) 