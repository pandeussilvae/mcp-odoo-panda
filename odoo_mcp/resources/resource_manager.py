from typing import Dict, Any, List, Optional, Union
from mcp.types import Resource, ResourceTemplate
import logging
import json
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler

logger = logging.getLogger(__name__)

class OdooResourceManager:
    """Gestisce le risorse Odoo."""
    
    def __init__(self, handler: XMLRPCHandler):
        self.handler = handler
        self.resource_templates = self._get_resource_templates()
    
    def _get_resource_templates(self) -> List[ResourceTemplate]:
        """Definisce i template delle risorse disponibili."""
        return [
            ResourceTemplate(
                uriTemplate="odoo://{model}/{id}",
                name="Odoo Record",
                description="Rappresenta un singolo record in un modello Odoo",
                type="record",
                mimeType="application/json"
            ),
            ResourceTemplate(
                uriTemplate="odoo://{model}/list",
                name="Odoo Record List",
                description="Rappresenta una lista di record in un modello Odoo",
                type="list",
                mimeType="application/json"
            ),
            ResourceTemplate(
                uriTemplate="odoo://{model}/binary/{field}/{id}",
                name="Odoo Binary Field",
                description="Rappresenta il valore di un campo binario da un record Odoo",
                type="binary",
                mimeType="application/octet-stream"
            )
        ]
    
    def get_resource(self, uri: str, auth_details: Dict[str, Any]) -> Resource:
        """Ottiene una risorsa specifica."""
        # Parsing dell'URI
        parts = uri.replace("odoo://", "").split("/")
        model = parts[0]
        
        if len(parts) == 2 and parts[1] == "list":
            # Lista di record
            records = self.handler.execute_kw(
                model=model,
                method="search_read",
                args=[[], ["id", "name"]],
                kwargs={"limit": 100},
                uid=auth_details["uid"],
                password=auth_details["password"]
            )
            return Resource(
                uri=uri,
                mimeType="application/json",
                text=json.dumps(records)
            )
        
        elif len(parts) == 2:
            # Singolo record
            try:
                record_id = int(parts[1])
                record = self.handler.execute_kw(
                    model=model,
                    method="read",
                    args=[[record_id]],
                    kwargs={},
                    uid=auth_details["uid"],
                    password=auth_details["password"]
                )
                return Resource(
                    uri=uri,
                    mimeType="application/json",
                    text=json.dumps(record[0] if record else {})
                )
            except ValueError:
                raise ValueError(f"ID record non valido: {parts[1]}")
        
        elif len(parts) == 4 and parts[1] == "binary":
            # Campo binario
            field = parts[2]
            try:
                record_id = int(parts[3])
                data = self.handler.execute_kw(
                    model=model,
                    method="read",
                    args=[[record_id], [field]],
                    kwargs={},
                    uid=auth_details["uid"],
                    password=auth_details["password"]
                )
                binary = data[0][field] if data and field in data[0] else None
                return Resource(
                    uri=uri,
                    mimeType="application/octet-stream",
                    text=binary
                )
            except ValueError:
                raise ValueError(f"ID record non valido: {parts[3]}")
        
        raise ValueError(f"URI non valido: {uri}")
    
    def list_resources(self) -> List[ResourceTemplate]:
        """Lista tutti i template di risorse disponibili."""
        return self.resource_templates 