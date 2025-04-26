# Server Odoo MCP

<div align="center">
  <img src="assets/Odoo MCP Server.png" alt="Odoo MCP Server Logo" width="100%"/> 
</div>

## Sviluppato da

Questo modulo è stato sviluppato da [Paolo Nugnes](https://github.com/pandeussilvae) e [TechLab](https://www.techlab.it).

TechLab è una società specializzata nello sviluppo di soluzioni software personalizzate e nell'integrazione di sistemi aziendali. Visita il nostro sito web [www.techlab.it](https://www.techlab.it) per maggiori informazioni sui nostri servizi.

## Panoramica

Il Server Odoo MCP è un'interfaccia standardizzata per interagire con le istanze Odoo attraverso protocolli moderni. Fornisce supporto per XML-RPC e JSON-RPC, Server-Sent Events (SSE) e integrazione con il sistema bus di Odoo per aggiornamenti in tempo reale.

## Caratteristiche

- **Protocolli**:
  - XML-RPC e JSON-RPC per la comunicazione con Odoo
  - stdio per comunicazione diretta
  - SSE per aggiornamenti in tempo reale

- **Gestione Risorse**:
  - Accesso ai record Odoo
  - Gestione dei campi binari
  - Aggiornamenti in tempo reale attraverso il bus di Odoo

- **Strumenti**:
  - Ricerca e lettura record (odoo_search_read, odoo_read)
  - Creazione e aggiornamento record (odoo_create, odoo_write)
  - Eliminazione record (odoo_unlink)
  - Chiamata di metodi personalizzati (odoo_call_method)

- **Sicurezza**:
  - Autenticazione e gestione sessioni
  - Rate limiting
  - CORS per connessioni SSE

## Requisiti

- Python 3.9+
- Odoo 15.0+
- Docker (opzionale)

## Installazione

### Installazione Diretta

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

# Copia il file di configurazione di esempio
cp odoo_mcp/config/config.example.yaml odoo_mcp/config/config.yaml

# Modifica config.yaml con le tue impostazioni
# nano odoo_mcp/config/config.yaml
```

### Installazione con Docker

```bash
# Clona il repository
git clone https://github.com/pandeussilvae/mcp-odoo-panda.git
cd mcp-odoo-panda

# Avvia con Docker Compose
docker-compose up -d
```

## Configurazione

Il server può essere configurato attraverso un file YAML. Sono disponibili diversi template di configurazione:

- `config.example.yaml`: Template principale da copiare e modificare
- `config.dev.yaml`: Template per ambiente di sviluppo (opzionale)
- `config.prod.yaml`: Template per ambiente di produzione (opzionale)

Per iniziare:

```bash
# Copia il file di configurazione di esempio
cp odoo_mcp/config/config.example.yaml odoo_mcp/config/config.yaml

# Modifica config.yaml con le tue impostazioni
# nano odoo_mcp/config/config.yaml
```

Esempio di configurazione base:

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

Per la configurazione avanzata, consulta i template `config.dev.yaml` e `config.prod.yaml` per esempi di configurazioni specifiche per ambiente.

## Utilizzo

### Connessione stdio

```python
import asyncio
from mcp.client import Client

async def main():
    client = Client(connection_type="stdio")
    await client.initialize()
    
    # Esempio: Leggi un record
    response = await client.read_resource("odoo://res.partner/1")
    print(response)

if __name__ == "__main__":
    asyncio.run(main())
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

## Documentazione

La documentazione completa è disponibile nella directory `docs/`:
- `server_usage.md`: Guida all'utilizzo del server

## Contribuire

1. Fork il repository
2. Crea un branch per la tua feature (`git checkout -b feature/amazing-feature`)
3. Commit le tue modifiche (`git commit -m 'Add amazing feature'`)
4. Push al branch (`git push origin feature/amazing-feature`)
5. Apri una Pull Request

## Licenza

Questo progetto è rilasciato sotto la licenza MIT. Vedi il file `LICENSE` per i dettagli.

---

# Odoo MCP Server

<div align="center">
  <img src="assets/Odoo MCP Server.png" alt="Odoo MCP Server Logo" width="100%"/> 
</div>

## Developed by

This module has been developed by [Paolo Nugnes](https://github.com/pandeussilvae) and [TechLab](https://www.techlab.it).

TechLab is a company specialized in custom software development and enterprise system integration. Visit our website [www.techlab.it](https://www.techlab.it) for more information about our services.

## Overview

The Odoo MCP Server is a standardized interface for interacting with Odoo instances through modern protocols. It provides support for XML-RPC and JSON-RPC, Server-Sent Events (SSE), and integration with Odoo's bus system for real-time updates.

## Features

- **Protocols**:
  - XML-RPC and JSON-RPC for Odoo communication
  - stdio for direct communication
  - SSE for real-time updates

- **Resource Management**:
  - Odoo record access
  - Binary field handling
  - Real-time updates through Odoo's bus system

- **Tools**:
  - Search and read records (odoo_search_read, odoo_read)
  - Create and update records (odoo_create, odoo_write)
  - Delete records (odoo_unlink)
  - Call custom methods (odoo_call_method)

- **Security**:
  - Authentication and session management
  - Rate limiting
  - CORS for SSE connections

## Requirements

- Python 3.9+
- Odoo 15.0+
- Docker (optional)

## Installation

### Direct Installation

```bash
# Clone the repository
git clone https://github.com/pandeussilvae/mcp-odoo-panda.git
cd mcp-odoo-panda

# Install dependencies
pip install .

# To install with caching support
pip install .[caching]

# To install with development tools
pip install .[dev]

# Copy example configuration file
cp odoo_mcp/config/config.example.yaml odoo_mcp/config/config.yaml

# Modify config.yaml with your settings
# nano odoo_mcp/config/config.yaml
```

### Docker Installation

```bash
# Clone the repository
git clone https://github.com/pandeussilvae/mcp-odoo-panda.git
cd mcp-odoo-panda

# Start with Docker Compose
docker-compose up -d
```

## Configuration

The server can be configured through a YAML file. There are different configuration templates available:

- `config.example.yaml`: Main template to copy and modify
- `config.dev.yaml`: Template for development environment (optional)
- `config.prod.yaml`: Template for production environment (optional)

To start:

```bash
# Copy example configuration file
cp odoo_mcp/config/config.example.yaml odoo_mcp/config/config.yaml

# Modify config.yaml with your settings
# nano odoo_mcp/config/config.yaml
```

Example of basic configuration:

```yaml
# config.yaml
protocol: xmlrpc  # or jsonrpc
connection_type: stdio  # or sse
odoo_url: http://localhost:8069
database: my_database
uid: admin
password: admin
requests_per_minute: 120
sse_queue_maxsize: 1000
allowed_origins: ["*"]  # for SSE connections
```

For advanced configuration, refer to the `config.dev.yaml` and `config.prod.yaml` templates for example specific environment configurations.

## Usage

### stdio Connection

```python
import asyncio
from mcp.client import Client

async def main():
    client = Client(connection_type="stdio")
    await client.initialize()
    
    # Example: Read a record
    response = await client.read_resource("odoo://res.partner/1")
    print(response)

if __name__ == "__main__":
    asyncio.run(main())
```

### SSE Connection

```javascript
// Connect to SSE endpoint
const eventSource = new EventSource('http://localhost:8080/events');

// Handle updates
eventSource.addEventListener('notifications/resources/updated', (event) => {
    const data = JSON.parse(event.data);
    console.log('Resource updated:', data.params.uri, data.params.data);
});
```

## Documentation

Complete documentation is available in the `docs/` directory:
- `server_usage.md`: Server usage guide

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is released under the MIT License. See the `LICENSE` file for details.
