import yaml
import json
from mcp_local_backup.server.fastmcp import FastMCP
import mcp_local_backup.types as types
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler

# Carica la configurazione Odoo
def load_odoo_config(path="odoo_mcp/config/config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

config = load_odoo_config()
odoo = XMLRPCHandler(config)

mcp = FastMCP("odoo-mcp-server")

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

@mcp.tool()
def odoo_search_read(model: str, domain: list, fields: list) -> list:
    records = odoo.execute_kw(
        model=model,
        method="search_read",
        args=[domain, fields],
        kwargs={},
    )
    return records

if __name__ == "__main__":
    mcp.run() 