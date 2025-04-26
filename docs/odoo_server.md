# Server Odoo MCP

Il server Odoo MCP implementa il protocollo MCP per l'integrazione con Odoo ERP. Fornisce un'interfaccia standardizzata per interagire con i record Odoo attraverso diversi protocolli di comunicazione.

## Caratteristiche

- **Protocolli di Comunicazione**:
  - stdio: Comunicazione diretta via stdin/stdout
  - SSE: Aggiornamenti in tempo reale via Server-Sent Events

- **Gestione Risorse**:
  - Record Odoo (singoli e liste)
  - Campi binari
  - Aggiornamenti in tempo reale

- **Strumenti**:
  - Ricerca e lettura record
  - Creazione e aggiornamento record
  - Eliminazione record
  - Chiamata di metodi personalizzati

- **Sicurezza**:
  - Autenticazione e gestione sessioni
  - Rate limiting
  - CORS per connessioni SSE

## Installazione

```bash
# Clona il repository
git clone https://github.com/pandeussilvae/mcp-odoo-panda.git
cd mcp-odoo-panda

# Installa le dipendenze
pip install .

# Per installare con supporto caching
pip install .[caching]

# Per installare con strumenti di sviluppo
pip install .[dev]
```

## Configurazione

Il server può essere configurato attraverso un file YAML:

```yaml
# config.yaml
protocol: xmlrpc  # o jsonrpc
connection_type: stdio  # o sse
odoo_url: http://localhost:8069
database: my_database
uid: admin
password: admin
requests_per_minute: 120
sse_queue_maxsize: 1000
allowed_origins: ["*"]  # per connessioni SSE
```

## Utilizzo

### Connessione stdio

```python
import asyncio
from mcp import Client

async def main():
    client = Client(connection_type="stdio")
    await client.initialize()
    
    # Esempio: Leggi un record
    resource = await client.get_resource("odoo://res.partner/1")
    print(resource.data)
```

### Connessione SSE

```javascript
// Connetti all'endpoint SSE
const eventSource = new EventSource('http://localhost:8080/events');

// Gestisci aggiornamenti
eventSource.addEventListener('notifications/resources/updated', (event) => {
    const data = JSON.parse(event.data);
    console.log('Risorsa aggiornata:', data.params.uri, data.params.data);
});
```

## API

### Risorse

#### Record Singolo
```
URI: odoo://{model}/{id}
Tipo: RECORD
MIME: application/json
```

#### Lista Record
```
URI: odoo://{model}/list
Tipo: LIST
MIME: application/json
```

#### Campo Binario
```
URI: odoo://{model}/binary/{field}/{id}
Tipo: BINARY
MIME: application/octet-stream
```

### Strumenti

#### odoo_search_read
```python
response = await client.call_tool("odoo_search_read", {
    "model": "res.partner",
    "domain": [["active", "=", True]],
    "fields": ["name", "email"],
    "limit": 10
})
```

#### odoo_read
```python
response = await client.call_tool("odoo_read", {
    "model": "res.partner",
    "ids": [1],
    "fields": ["name", "email"]
})
```

#### odoo_create
```python
response = await client.call_tool("odoo_create", {
    "model": "res.partner",
    "values": {
        "name": "Mario Rossi",
        "email": "mario.rossi@example.com"
    }
})
```

#### odoo_write
```python
response = await client.call_tool("odoo_write", {
    "model": "res.partner",
    "ids": [1],
    "values": {
        "name": "Mario Rossi Aggiornato"
    }
})
```

#### odoo_unlink
```python
response = await client.call_tool("odoo_unlink", {
    "model": "res.partner",
    "ids": [1]
})
```

#### odoo_call_method
```python
response = await client.call_tool("odoo_call_method", {
    "model": "res.partner",
    "method": "action_archive",
    "ids": [1]
})
```

### Prompt

#### analyze-record
```python
result = await client.get_prompt("analyze-record", {
    "uri": "odoo://res.partner/1"
})
```

#### create-record
```python
result = await client.get_prompt("create-record", {
    "model": "res.partner",
    "template": {"name": "Nuovo Partner"}
})
```

#### update-record
```python
result = await client.get_prompt("update-record", {
    "uri": "odoo://res.partner/1"
})
```

#### advanced-search
```python
result = await client.get_prompt("advanced-search", {
    "model": "res.partner",
    "fields": ["name", "email"]
})
```

#### call-method
```python
result = await client.get_prompt("call-method", {
    "uri": "odoo://res.partner/1",
    "method": "action_archive"
})
```

## Best Practices

1. **Gestione delle Connessioni**:
   - Chiudi sempre le connessioni correttamente
   - Gestisci la logica di riconnessione per le connessioni SSE
   - Monitora lo stato delle connessioni

2. **Utilizzo delle Risorse**:
   - Usa limiti appropriati per le operazioni di ricerca
   - Annulla le sottoscrizioni quando non più necessarie
   - Gestisci i dati binari in modo efficiente

3. **Gestione degli Errori**:
   - Implementa una corretta gestione degli errori
   - Registra gli errori appropriatamente
   - Fornisci messaggi di errore comprensibili

4. **Sicurezza**:
   - Usa metodi di autenticazione sicuri
   - Implementa politiche CORS appropriate
   - Monitora i limiti di richiesta

5. **Performance**:
   - Usa la cache quando appropriato
   - Esegui operazioni in batch quando possibile
   - Monitora l'utilizzo della memoria 