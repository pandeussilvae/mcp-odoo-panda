from typing import Dict, Any, Optional
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler

class OdooToolManager:
    """Gestisce gli strumenti per le operazioni Odoo."""
    
    def __init__(self, odoo: XMLRPCHandler):
        """Inizializza il gestore degli strumenti.
        
        Args:
            odoo: Istanza di XMLRPCHandler per la comunicazione con Odoo
        """
        self.odoo = odoo
        self._register_default_tools()
    
    def _register_default_tools(self):
        """Registra gli strumenti predefiniti."""
        self.tools = {
            "search": {
                "description": "Cerca record in un modello Odoo",
                "parameters": {
                    "model": "Nome del modello",
                    "domain": "Dominio di ricerca",
                    "fields": "Campi da recuperare"
                }
            },
            "create": {
                "description": "Crea un nuovo record in un modello Odoo",
                "parameters": {
                    "model": "Nome del modello",
                    "values": "Valori per il nuovo record"
                }
            },
            "write": {
                "description": "Aggiorna un record esistente in un modello Odoo",
                "parameters": {
                    "model": "Nome del modello",
                    "id": "ID del record",
                    "values": "Valori da aggiornare"
                }
            },
            "unlink": {
                "description": "Elimina un record da un modello Odoo",
                "parameters": {
                    "model": "Nome del modello",
                    "id": "ID del record"
                }
            }
        }
    
    def execute_tool(self, tool_name: str, **kwargs) -> Any:
        """Esegue uno strumento specifico.
        
        Args:
            tool_name: Nome dello strumento da eseguire
            **kwargs: Parametri per lo strumento
            
        Returns:
            Risultato dell'esecuzione dello strumento
            
        Raises:
            ValueError: Se lo strumento non esiste o se mancano parametri richiesti
        """
        if tool_name not in self.tools:
            raise ValueError(f"Strumento '{tool_name}' non trovato")
            
        tool = self.tools[tool_name]
        required_params = tool["parameters"].keys()
        
        # Verifica che tutti i parametri richiesti siano presenti
        missing_params = [param for param in required_params if param not in kwargs]
        if missing_params:
            raise ValueError(f"Parametri mancanti per lo strumento '{tool_name}': {', '.join(missing_params)}")
            
        # Esegui lo strumento appropriato
        if tool_name == "search":
            return self.odoo.execute_kw(
                model=kwargs["model"],
                method="search_read",
                args=[kwargs.get("domain", []), kwargs.get("fields", ["id", "name"])],
                kwargs={}
            )
        elif tool_name == "create":
            return self.odoo.execute_kw(
                model=kwargs["model"],
                method="create",
                args=[kwargs["values"]],
                kwargs={}
            )
        elif tool_name == "write":
            return self.odoo.execute_kw(
                model=kwargs["model"],
                method="write",
                args=[[kwargs["id"]], kwargs["values"]],
                kwargs={}
            )
        elif tool_name == "unlink":
            return self.odoo.execute_kw(
                model=kwargs["model"],
                method="unlink",
                args=[[kwargs["id"]]],
                kwargs={}
            )
    
    def list_tools(self) -> Dict[str, Dict[str, Any]]:
        """Lista tutti gli strumenti disponibili.
        
        Returns:
            Dizionario con tutti gli strumenti e le loro descrizioni
        """
        return self.tools
    
    def register_tool(self, name: str, description: str, parameters: Dict[str, str]):
        """Registra un nuovo strumento.
        
        Args:
            name: Nome dello strumento
            description: Descrizione dello strumento
            parameters: Dizionario dei parametri richiesti e le loro descrizioni
        """
        self.tools[name] = {
            "description": description,
            "parameters": parameters
        } 