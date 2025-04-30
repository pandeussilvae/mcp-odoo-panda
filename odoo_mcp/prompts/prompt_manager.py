from typing import Dict, Any, List, Optional
from mcp.types import Prompt, PromptArgument, GetPromptResult, PromptMessage, TextContent
import logging

logger = logging.getLogger(__name__)

class OdooPromptManager:
    """Gestisce i prompt per le operazioni Odoo."""
    
    def __init__(self):
        self.prompts: Dict[str, Prompt] = {}
        self._register_default_prompts()
    
    def _register_default_prompts(self):
        """Registra i prompt predefiniti."""
        self.register_prompt(
            name="analyze_record",
            description="Analizza un record Odoo specifico",
            arguments=[
                PromptArgument(name="model", description="Nome del modello Odoo", required=True),
                PromptArgument(name="id", description="ID del record", required=True)
            ]
        )
        
        self.register_prompt(
            name="create_record",
            description="Crea un nuovo record in Odoo",
            arguments=[
                PromptArgument(name="model", description="Nome del modello Odoo", required=True),
                PromptArgument(name="values", description="Valori per il nuovo record", required=True)
            ]
        )
        
        self.register_prompt(
            name="update_record",
            description="Aggiorna un record esistente in Odoo",
            arguments=[
                PromptArgument(name="model", description="Nome del modello Odoo", required=True),
                PromptArgument(name="id", description="ID del record", required=True),
                PromptArgument(name="values", description="Valori da aggiornare", required=True)
            ]
        )
    
    def register_prompt(self, name: str, description: str, arguments: List[PromptArgument]):
        """Registra un nuovo prompt."""
        self.prompts[name] = Prompt(
            name=name,
            description=description,
            arguments=arguments
        )
        logger.info(f"Registrato prompt: {name}")
    
    def get_prompt(self, name: str, arguments: Optional[Dict[str, str]] = None) -> GetPromptResult:
        """Ottiene un prompt specifico con i suoi argomenti."""
        if name not in self.prompts:
            raise ValueError(f"Prompt non trovato: {name}")
        
        prompt = self.prompts[name]
        messages = []
        
        # Costruisci il messaggio base
        base_message = f"Esegui l'operazione {prompt.name} con i seguenti parametri:\n"
        for arg in prompt.arguments:
            value = arguments.get(arg.name, "non specificato") if arguments else "non specificato"
            base_message += f"- {arg.name}: {value}\n"
        
        messages.append(
            PromptMessage(
                role="system",
                content=TextContent(
                    type="text",
                    text=base_message
                )
            )
        )
        
        return GetPromptResult(
            description=prompt.description,
            messages=messages
        )
    
    def list_prompts(self) -> List[Prompt]:
        """Lista tutti i prompt disponibili."""
        return list(self.prompts.values()) 