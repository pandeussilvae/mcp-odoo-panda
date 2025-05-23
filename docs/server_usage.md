# Documentazione Server Odoo MCP

## Panoramica

Il Server Odoo MCP fornisce un'interfaccia standardizzata per interagire con le istanze Odoo attraverso i protocolli stdio e Server-Sent Events (SSE). Supporta aggiornamenti in tempo reale, gestione delle risorse e un set completo di strumenti per le operazioni Odoo.

## Funzionalità

- **Tipi di Connessione**:
  - stdio: Per comunicazione diretta tra processi
  - SSE: Per comunicazione web in tempo reale

- **Gestione delle Risorse**:
  - Accesso e manipolazione dei record
  - Gestione dei campi binari
  - Aggiornamenti in tempo reale attraverso il sistema bus di Odoo

- **Strumenti**:
  - Ricerca e lettura dei record
  - Creazione, aggiornamento ed eliminazione dei record
  - Chiamata di metodi personalizzati
  - Capacità di ricerca avanzata

- **Sicurezza**:
  - Autenticazione e gestione delle sessioni
  - Limitazione delle richieste
  - Supporto CORS per connessioni SSE

## Metodi di Connessione

### 1. Connessione stdio

La connessione stdio è ideale per la comunicazione diretta tra processi. È il tipo di connessione predefinito e fornisce il metodo di comunicazione più efficiente.

Esempio client Python:
```python
import asyncio
import json
from mcp.client import Client

async def main():
    # Crea client con connessione stdio
    client = Client(connection_type="stdio")
    
    # Inizializza connessione
    await client.initialize()
    
    # Esempio: Leggi un record
    response = await client.read_resource("odoo://res.partner/1")
    print(json.dumps(response, indent=2))
    
    # Esempio: Cerca record
    response = await client.call_tool("odoo_search_read", {
        "model": "res.partner",
        "domain": [["active", "=", True]],
        "fields": ["name", "email"]
    })
    print(json.dumps(response, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
```

### 2. Connessione SSE

La connessione SSE è progettata per applicazioni web che richiedono aggiornamenti in tempo reale. Fornisce una connessione persistente per ricevere eventi dal server.

Esempio client JavaScript:
```javascript
// Connetti all'endpoint SSE
const eventSource = new EventSource('http://localhost:8080/events');

// Gestisci connessione stabilita
eventSource.addEventListener('notifications/connection/established', (event) => {
    const data = JSON.parse(event.data);
    console.log('Connesso con ID cliente:', data.params.client_id);
});

// Gestisci aggiornamenti risorse
eventSource.addEventListener('notifications/resources/updated', (event) => {
    const data = JSON.parse(event.data);
    console.log('Risorsa aggiornata:', data.params.uri, data.params.data);
});

// Esempio: Invia una richiesta
async function searchPartners() {
    const response = await fetch('http://localhost:8080/mcp', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            jsonrpc: "2.0",
            method: "call_tool",
            params: {
                name: "odoo_search_read",
                arguments: {
                    model: "res.partner",
                    domain: [["active", "=", true]],
                    fields: ["name", "email"],
                    limit: 10,
                    offset: 0
                }
            }
        })
    });
    return response.json();
}
```

## Tipi di Risorse

### 1. Risorsa Record
```
odoo://{model}/{id}
```
Esempio: `odoo://res.partner/1`

### 2. Risorsa Lista
```
odoo://{model}/list
```
Esempio: `odoo://res.partner/list`

### 3. Risorsa Campo Binario
```
odoo://{model}/binary/{field}/{id}
```
Esempio: `odoo://ir.attachment/binary/datas/1`

## Strumenti

### 1. odoo_search_read
```python
response = await client.call_tool("odoo_search_read", {
    "model": "res.partner",
    "domain": [["active", "=", True]],
    "fields": ["name", "email"],
    "limit": 10,
    "offset": 0
})
```

### 2. odoo_read
```python
response = await client.call_tool("odoo_read", {
    "model": "res.partner",
    "ids": [1, 2, 3],
    "fields": ["name", "email"]
})
```

### 3. odoo_create
```python
response = await client.call_tool("odoo_create", {
    "model": "res.partner",
    "values": {
        "name": "John Doe",
        "email": "john@example.com"
    }
})
```

### 4. odoo_write
```python
response = await client.call_tool("odoo_write", {
    "model": "res.partner",
    "ids": [1],
    "values": {
        "name": "John Doe Updated"
    }
})
```

### 5. odoo_unlink
```python
response = await client.call_tool("odoo_unlink", {
    "model": "res.partner",
    "ids": [1]
})
```

### 6. odoo_call_method
```python
response = await client.call_tool("odoo_call_method", {
    "model": "res.partner",
    "method": "name_get",
    "args": [[1]],
    "kwargs": {}
})
```

## Aggiornamenti in Tempo Reale

### Sottoscrizione agli Aggiornamenti
```python
# Sottoscrivi agli aggiornamenti del record
await client.subscribe_resource("odoo://res.partner/1")

# Il client riceverà notifiche quando il record viene aggiornato
```

### Annullamento Sottoscrizione
```python
# Annulla la sottoscrizione agli aggiornamenti del record
await client.unsubscribe_resource("odoo://res.partner/1")
```

## Configurazione

Il server può essere configurato attraverso un file di configurazione YAML:

```yaml
# config.yaml
protocol: jsonrpc # or xmlrpc
connection_type: stdio  # or sse
odoo_url: http://localhost:8069
database: mio_database
uid: admin
password: admin
requests_per_minute: 120
sse_queue_maxsize: 1000
allowed_origins: ["*"]  # per connessioni SSE
```

## Gestione degli Errori

Il server fornisce risposte di errore dettagliate in formato JSON-RPC:

```json
{
    "jsonrpc": "2.0",
    "id": "request_id",
    "error": {
        "code": -32000,
        "message": "Descrizione errore"
    }
}
```

Codici di errore comuni:
- -32700: Errore di parsing
- -32603: Errore interno
- -32000: Errore applicativo
- -32001: Server occupato
- -32002: Richiesta non valida
- -32003: Metodo non trovato
- -32004: Parametri non validi

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

## Risoluzione dei Problemi

### Problemi Comuni

1. **Problemi di Connessione**:
   - Verifica la disponibilità del server Odoo
   - Controlla le credenziali di autenticazione
   - Verifica la connettività di rete

2. **Problemi di Connessione SSE**:
   - Verifica la configurazione CORS
   - Controlla il supporto del browser client
   - Monitora i log del server

3. **Problemi di Performance**:
   - Controlla i limiti di richiesta
   - Monitora le risorse del server
   - Rivedi l'ottimizzazione delle query

### Logging

Il server fornisce un logging dettagliato. Abilita i livelli di log appropriati nella configurazione:

```yaml
logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  handlers:
    - type: StreamHandler
      level: INFO
    - type: FileHandler
      filename: server.log
      level: DEBUG
```

## Utilizzo con Docker

### Configurazione Docker

Il server MCP può essere eseguito come container Docker. Ecco un esempio di configurazione:

```dockerfile
# Dockerfile
FROM python:3.9-slim

# Installa le dipendenze di sistema
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Crea e imposta la directory di lavoro
WORKDIR /app

# Copia i file di requisiti
COPY requirements.txt .

# Installa le dipendenze Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia il codice dell'applicazione
COPY . .

# Esponi la porta per SSE
EXPOSE 8080

# Comando di avvio
CMD ["python", "-m", "odoo_mcp.core.mcp_server"]
```

### File di Configurazione Docker

```yaml
# docker-compose.yml
version: '3.8'

services:
  mcp-server:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - ./config:/app/config
    environment:
      - ODOO_URL=http://odoo:8069
      - DATABASE=my_database
      - UID=admin
      - PASSWORD=admin
    depends_on:
      - odoo

  odoo:
    image: odoo:18.0
    ports:
      - "8069:8069"
    volumes:
      - odoo-data:/var/lib/odoo
    environment:
      - POSTGRES_DB=my_database
      - POSTGRES_USER=odoo
      - POSTGRES_PASSWORD=odoo

volumes:
  odoo-data:
```

### Avvio del Server

1. **Build e avvio dei container**:
```bash
docker-compose up --build
```

2. **Verifica dello stato**:
```bash
docker-compose ps
```

3. **Visualizzazione dei log**:
```bash
docker-compose logs -f mcp-server
```

### Configurazione Avanzata

#### Variabili d'Ambiente
```yaml
# docker-compose.yml
services:
  mcp-server:
    environment:
      - PROTOCOL=jsonrpc
      - CONNECTION_TYPE=sse
      - REQUESTS_PER_MINUTE=120
      - SSE_QUEUE_MAXSIZE=1000
      - ALLOWED_ORIGINS=["*"]
```

#### Volumi
```yaml
# docker-compose.yml
services:
  mcp-server:
    volumes:
      - ./config:/app/config
      - ./logs:/app/logs
```

#### Rete
```yaml
# docker-compose.yml
services:
  mcp-server:
    networks:
      - odoo-network

networks:
  odoo-network:
    driver: bridge
```

### Best Practices per Docker

1. **Sicurezza**:
   - Non esporre porte non necessarie
   - Usa segreti per le credenziali
   - Limita i permessi del container

2. **Performance**:
   - Usa volumi per i dati persistenti
   - Configura i limiti di risorse
   - Monitora l'utilizzo delle risorse

3. **Manutenzione**:
   - Aggiorna regolarmente le immagini
   - Pulisci i container non utilizzati
   - Monitora i log

4. **Scalabilità**:
   - Usa Docker Swarm o Kubernetes per il clustering
   - Configura il bilanciamento del carico
   - Implementa health checks

### Esempio di Health Check

```yaml
# docker-compose.yml
services:
  mcp-server:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### Monitoraggio

```yaml
# docker-compose.yml
services:
  mcp-server:
    labels:
      - "prometheus.enable=true"
      - "prometheus.port=8080"
      - "prometheus.path=/metrics"
```

### Backup e Ripristino

```bash
# Backup della configurazione
docker cp mcp-server:/app/config ./backup/config

# Ripristino della configurazione
docker cp ./backup/config mcp-server:/app/config
```

---

# Odoo MCP Server Documentation (English Version)

## Overview

The Odoo MCP Server provides a standardized interface for interacting with Odoo instances through both stdio and Server-Sent Events (SSE) protocols. It supports real-time updates, resource management, and a comprehensive set of tools for Odoo operations.

## Features

- **Multiple Connection Types**:
  - stdio: For direct process communication
  - SSE: For web-based real-time communication

- **Resource Management**:
  - Record access and manipulation
  - Binary field handling
  - Real-time updates through Odoo's bus system

- **Tools**:
  - Search and read records
  - Create, update, and delete records
  - Call custom methods
  - Advanced search capabilities

- **Security**:
  - Authentication and session management
  - Rate limiting
  - CORS support for SSE connections

## Connection Methods

### 1. stdio Connection

The stdio connection is ideal for direct process-to-process communication. It's the default connection type and provides the most efficient communication method.

Example Python client:
```python
import asyncio
import json
from mcp.client import Client

async def main():
    # Create client with stdio connection
    client = Client(connection_type="stdio")
    
    # Initialize connection
    await client.initialize()
    
    # Example: Read a record
    response = await client.read_resource("odoo://res.partner/1")
    print(json.dumps(response, indent=2))
    
    # Example: Search records
    response = await client.call_tool("odoo_search_read", {
        "model": "res.partner",
        "domain": [["active", "=", True]],
        "fields": ["name", "email"]
    })
    print(json.dumps(response, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
```

### 2. SSE Connection

The SSE connection is designed for web applications requiring real-time updates. It provides a persistent connection for receiving server events.

Example JavaScript client:
```javascript
// Connect to SSE endpoint
const eventSource = new EventSource('http://localhost:8080/events');

// Handle connection established
eventSource.addEventListener('notifications/connection/established', (event) => {
    const data = JSON.parse(event.data);
    console.log('Connected with client ID:', data.params.client_id);
});

// Handle resource updates
eventSource.addEventListener('notifications/resources/updated', (event) => {
    const data = JSON.parse(event.data);
    console.log('Resource updated:', data.params.uri, data.params.data);
});

// Example: Send a request
async function searchPartners() {
    const response = await fetch('http://localhost:8080/mcp', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            jsonrpc: "2.0",
            method: "call_tool",
            params: {
                name: "odoo_search_read",
                arguments: {
                    model: "res.partner",
                    domain: [["active", "=", true]],
                    fields: ["name", "email"],
                    limit: 10,
                    offset: 0
                }
            }
        })
    });
    return response.json();
}
```

## Resource Types

### 1. Record Resource
```
odoo://{model}/{id}
```
Example: `odoo://res.partner/1`

### 2. List Resource
```
odoo://{model}/list
```
Example: `odoo://res.partner/list`

### 3. Binary Field Resource
```
odoo://{model}/binary/{field}/{id}
```
Example: `odoo://ir.attachment/binary/datas/1`

## Tools

### 1. odoo_search_read
```python
response = await client.call_tool("odoo_search_read", {
    "model": "res.partner",
    "domain": [["active", "=", True]],
    "fields": ["name", "email"],
    "limit": 10,
    "offset": 0
})
```

### 2. odoo_read
```python
response = await client.call_tool("odoo_read", {
    "model": "res.partner",
    "ids": [1, 2, 3],
    "fields": ["name", "email"]
})
```

### 3. odoo_create
```python
response = await client.call_tool("odoo_create", {
    "model": "res.partner",
    "values": {
        "name": "John Doe",
        "email": "john@example.com"
    }
})
```

### 4. odoo_write
```python
response = await client.call_tool("odoo_write", {
    "model": "res.partner",
    "ids": [1],
    "values": {
        "name": "John Doe Updated"
    }
})
```

### 5. odoo_unlink
```python
response = await client.call_tool("odoo_unlink", {
    "model": "res.partner",
    "ids": [1]
})
```

### 6. odoo_call_method
```python
response = await client.call_tool("odoo_call_method", {
    "model": "res.partner",
    "method": "name_get",
    "args": [[1]],
    "kwargs": {}
})
```

## Real-time Updates

### Subscribing to Updates
```python
# Subscribe to record updates
await client.subscribe_resource("odoo://res.partner/1")

# The client will receive notifications when the record is updated
```

### Unsubscribing from Updates
```python
# Unsubscribe from record updates
await client.unsubscribe_resource("odoo://res.partner/1")
```

## Configuration

The server can be configured through a YAML configuration file:

```yaml
# config.yaml
protocol: jsonrpc # or xmlrpc
connection_type: stdio  # or sse
odoo_url: http://localhost:8069
database: my_database
uid: admin
password: admin
requests_per_minute: 120
sse_queue_maxsize: 1000
allowed_origins: ["*"]  # for SSE connections
```

## Error Handling

The server provides detailed error responses in JSON-RPC format:

```json
{
    "jsonrpc": "2.0",
    "id": "request_id",
    "error": {
        "code": -32000,
        "message": "Error description"
    }
}
```

Common error codes:
- -32700: Parse error
- -32603: Internal error
- -32000: Application error
- -32001: Server busy
- -32002: Invalid request
- -32003: Method not found
- -32004: Invalid params

## Best Practices

1. **Connection Management**:
   - Always close connections properly
   - Handle reconnection logic for SSE connections
   - Monitor connection health

2. **Resource Usage**:
   - Use appropriate limits for search operations
   - Unsubscribe from updates when no longer needed
   - Handle binary data efficiently

3. **Error Handling**:
   - Implement proper error handling for all operations
   - Log errors appropriately
   - Provide user-friendly error messages

4. **Security**:
   - Use secure authentication methods
   - Implement proper CORS policies
   - Monitor rate limits

5. **Performance**:
   - Use caching when appropriate
   - Batch operations when possible
   - Monitor memory usage

## Troubleshooting

### Common Issues

1. **Connection Issues**:
   - Check Odoo server availability
   - Verify authentication credentials
   - Check network connectivity

2. **SSE Connection Problems**:
   - Verify CORS configuration
   - Check client browser support
   - Monitor server logs

3. **Performance Issues**:
   - Check rate limits
   - Monitor server resources
   - Review query optimization

### Logging

The server provides detailed logging. Enable appropriate log levels in the configuration:

```yaml
logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  handlers:
    - type: StreamHandler
      level: INFO
    - type: FileHandler
      filename: server.log
      level: DEBUG
```

## Docker Usage

### Docker Configuration

The MCP server can be run as a Docker container. Here's an example configuration:

```dockerfile
# Dockerfile
FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create and set working directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port for SSE
EXPOSE 8080

# Start command
CMD ["python", "-m", "odoo_mcp.core.mcp_server"]
```

### Docker Configuration File

```yaml
# docker-compose.yml
version: '3.8'

services:
  mcp-server:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - ./config:/app/config
    environment:
      - ODOO_URL=http://odoo:8069
      - DATABASE=my_database
      - UID=admin
      - PASSWORD=admin
    depends_on:
      - odoo

  odoo:
    image: odoo:15.0
    ports:
      - "8069:8069"
    volumes:
      - odoo-data:/var/lib/odoo
    environment:
      - POSTGRES_DB=my_database
      - POSTGRES_USER=odoo
      - POSTGRES_PASSWORD=odoo

volumes:
  odoo-data:
```

### Starting the Server

1. **Build and start containers**:
```bash
docker-compose up --build
```

2. **Check status**:
```bash
docker-compose ps
```

3. **View logs**:
```bash
docker-compose logs -f mcp-server
```

### Advanced Configuration

#### Environment Variables
```yaml
# docker-compose.yml
services:
  mcp-server:
    environment:
      - PROTOCOL=jsonrpc
      - CONNECTION_TYPE=sse
      - REQUESTS_PER_MINUTE=120
      - SSE_QUEUE_MAXSIZE=1000
      - ALLOWED_ORIGINS=["*"]
```

#### Volumes
```yaml
# docker-compose.yml
services:
  mcp-server:
    volumes:
      - ./config:/app/config
      - ./logs:/app/logs
```

#### Network
```yaml
# docker-compose.yml
services:
  mcp-server:
    networks:
      - odoo-network

networks:
  odoo-network:
    driver: bridge
```

### Docker Best Practices

1. **Security**:
   - Don't expose unnecessary ports
   - Use secrets for credentials
   - Limit container permissions

2. **Performance**:
   - Use volumes for persistent data
   - Configure resource limits
   - Monitor resource usage

3. **Maintenance**:
   - Regularly update images
   - Clean up unused containers
   - Monitor logs

4. **Scalability**:
   - Use Docker Swarm or Kubernetes for clustering
   - Configure load balancing
   - Implement health checks

### Health Check Example

```yaml
# docker-compose.yml
services:
  mcp-server:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### Monitoring

```yaml
# docker-compose.yml
services:
  mcp-server:
    labels:
      - "prometheus.enable=true"
      - "prometheus.port=8080"
      - "prometheus.path=/metrics"
```

### Backup and Restore

```bash
# Backup configuration
docker cp mcp-server:/app/config ./backup/config

# Restore configuration
docker cp ./backup/config mcp-server:/app/config
``` 
