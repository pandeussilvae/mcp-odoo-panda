# MCP (Model Context Protocol)

Il modulo MCP fornisce l'implementazione base del protocollo Model Context Protocol, un'interfaccia standardizzata per l'interazione con modelli di dati attraverso diversi protocolli di comunicazione.

## Struttura del Modulo

```
mcp/
├── types.py           # Definizioni dei tipi MCP
├── server.py          # Classe base del server MCP
└── protocol/          # Implementazioni dei protocolli
    ├── stdio.py       # Protocollo stdio
    └── sse.py         # Protocollo Server-Sent Events
```

## Tipi di Dati

### ResourceType
```python
class ResourceType(Enum):
    RECORD = "record"    # Singolo record
    LIST = "list"        # Lista di record
    BINARY = "binary"    # Campo binario
```

### Resource
```python
@dataclass
class Resource:
    uri: str            # URI del record
    type: ResourceType  # Tipo di risorsa
    data: Any          # Dati della risorsa
    mime_type: str     # Tipo MIME (default: "application/json")
```

### Tool
```python
@dataclass
class Tool:
    name: str           # Nome dello strumento
    description: str    # Descrizione dello strumento
    input_schema: Dict[str, Any]  # Schema di input JSON
```

### Prompt
```python
@dataclass
class Prompt:
    name: str           # Nome del prompt
    description: str    # Descrizione del prompt
    arguments: List[Dict[str, Any]]  # Argomenti del prompt
```

## Server MCP

La classe `MCPServer` fornisce l'implementazione base di un server MCP. Le implementazioni specifiche (come OdooMCPServer) devono estendere questa classe e implementare i metodi astratti.

### Metodi Principali

```python
class MCPServer(ABC):
    async def initialize(self, client_info: ClientInfo) -> ServerInfo:
        """Inizializza il server con le informazioni del client."""

    async def get_resource(self, uri: str) -> Resource:
        """Ottiene una risorsa tramite URI."""

    async def list_resources(self, template: Optional[ResourceTemplate] = None) -> List[Resource]:
        """Elenca le risorse disponibili."""

    async def list_tools(self) -> List[Tool]:
        """Elenca gli strumenti disponibili."""

    async def list_prompts(self) -> List[Prompt]:
        """Elenca i prompt disponibili."""

    async def get_prompt(self, name: str, args: Dict[str, Any]) -> GetPromptResult:
        """Ottiene un prompt specifico."""
```

## Protocolli di Comunicazione

### Stdio Protocol

Il protocollo stdio utilizza stdin/stdout per la comunicazione JSON-RPC:

```python
class StdioProtocol:
    async def run(self):
        """Esegue il server in modalità stdio."""

    def stop(self):
        """Ferma il server."""
```

### SSE Protocol

Il protocollo SSE (Server-Sent Events) fornisce aggiornamenti in tempo reale:

```python
class SSEProtocol:
    async def run(self, host: str = "localhost", port: int = 8080):
        """Esegue il server in modalità SSE."""

    async def broadcast(self, message: Dict[str, Any]):
        """Invia un messaggio a tutti i client connessi."""

    def stop(self):
        """Ferma il server."""
```

## Utilizzo

### Esempio di Server Base

```python
from mcp import MCPServer, Resource, ResourceType

class MyServer(MCPServer):
    def __init__(self):
        super().__init__("my-server", "1.0.0")

    @property
    def capabilities(self) -> Dict[str, Any]:
        return {
            "resources": {
                "templates": [
                    {
                        "uriTemplate": "my://resource/{id}",
                        "name": "My Resource",
                        "description": "A custom resource"
                    }
                ]
            }
        }

    async def get_resource(self, uri: str) -> Resource:
        # Implementazione specifica
        return Resource(
            uri=uri,
            type=ResourceType.RECORD,
            data={"id": 1, "name": "Example"},
            mime_type="application/json"
        )
```

### Esempio di Client

```python
import asyncio
from mcp import Client

async def main():
    client = Client(connection_type="stdio")
    await client.initialize()
    
    # Ottieni una risorsa
    resource = await client.get_resource("my://resource/1")
    print(resource.data)
```

## Best Practices

1. **Gestione delle Risorse**:
   - Usa URI consistenti e ben strutturati
   - Implementa la validazione degli URI
   - Gestisci appropriatamente i tipi MIME

2. **Sicurezza**:
   - Implementa l'autenticazione
   - Valida gli input
   - Gestisci gli errori in modo appropriato

3. **Performance**:
   - Usa la cache quando appropriato
   - Implementa il rate limiting
   - Ottimizza le query al database

4. **Manutenzione**:
   - Documenta le API
   - Aggiungi logging appropriato
   - Scrivi test unitari 