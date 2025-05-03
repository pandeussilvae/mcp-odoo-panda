# Server Odoo MCP

<div align="center">
  <img src="assets/Odoo MCP Server.png" alt="Odoo MCP Server Logo" width="100%"/> 
</div>

## Sviluppato da

Questo modulo è stato sviluppato da [Paolo Nugnes](https://github.com/pandeussilvae) e [TechLab](https://www.techlab.it).

TechLab è una società specializzata nello sviluppo di soluzioni software personalizzate e nell'integrazione di sistemi aziendali. Visita il nostro sito web [www.techlab.it](https://www.techlab.it) per maggiori informazioni sui nostri servizi.

## Panoramica

Il Server Odoo MCP è un'interfaccia standardizzata per interagire con le istanze Odoo attraverso il protocollo MCP (Model Context Protocol). Fornisce supporto per:

- **Protocolli di Comunicazione**:
  - stdio: Comunicazione diretta via stdin/stdout
  - streamable_http: Comunicazione HTTP con supporto per streaming delle risposte

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
  - CORS per connessioni streamable_http

## Requisiti di Sistema

### Requisiti Hardware
- CPU: 2+ core
- RAM: 4GB minimo (8GB raccomandato)
- Spazio Disco: 1GB minimo

### Requisiti Software
- Python 3.9+
- Odoo 15.0+
  - Moduli necessari: base, web, bus
  - Configurazione del database con utente admin
- Docker (opzionale)

### Requisiti di Rete
- Porta 8069 (Odoo)
- Porta 8080 (streamable_http, opzionale)
- Porta 5432 (PostgreSQL, se locale)

### Requisiti di Sicurezza
- Certificato SSL per HTTPS (produzione)
- Firewall configurato
- Accesso VPN (opzionale)

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
cp odoo_mcp/config/config.example.json odoo_mcp/config/config.json

# Modifica config.json con le tue impostazioni
# nano odoo_mcp/config/config.json
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

Il server può essere configurato attraverso un file JSON. Sono disponibili diversi template di configurazione:

- `config.example.json`: Template principale da copiare e modificare
- `config.dev.json`: Template per ambiente di sviluppo (opzionale)
- `config.prod.json`: Template per ambiente di produzione (opzionale)

Per iniziare:

```bash
# Copia il file di configurazione di esempio
cp odoo_mcp/config/config.example.json odoo_mcp/config/config.json

# Modifica config.json con le tue impostazioni
# nano odoo_mcp/config/config.json
```

Esempio di configurazione completa:

```json
{
    "mcpServers": {
        "mcp-odoo-panda": {
            "command": "/usr/bin/python3",
            "args": [
                "--directory",
                "/path/to/mcp-odoo-panda",
                "mcp/server.py",
                "--config",
                "/path/to/mcp-odoo-panda/odoo_mcp/config/config.json"
            ]
        }
    },
    "odoo_url": "http://localhost:8069",
    "database": "my_database",
    "username": "admin",
    "api_key": "admin",
    "protocol": "xmlrpc",
    "connection_type": "stdio",
    "requests_per_minute": 120,
    "rate_limit_max_wait_seconds": 5,
    "pool_size": 5,
    "timeout": 30,
    "session_timeout_minutes": 60,
    "http": {
        "host": "0.0.0.0",
        "port": 8080,
        "streamable": false
    },
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        "handlers": [
            {
                "type": "StreamHandler",
                "level": "INFO"
            },
            {
                "type": "FileHandler",
                "filename": "server.log",
                "level": "DEBUG"
            }
        ]
    }
}
```

## Avvio del Server

Il server può essere avviato in due modalità: stdio (default) e streamable_http. Il file di configurazione è opzionale e, se non specificato, il server cercherà automaticamente il file in `odoo_mcp/config/config.json`.

### Modalità stdio (default)

```bash
# Avvia il server in modalità stdio senza specificare il file di configurazione
python -m odoo_mcp.server

# Avvia il server in modalità stdio con un file di configurazione specifico
python -m odoo_mcp.server /path/to/config.json
```

### Modalità streamable_http

```bash
# Avvia il server in modalità streamable_http senza specificare il file di configurazione
python -m odoo_mcp.server streamable_http

# Avvia il server in modalità streamable_http con un file di configurazione specifico
python -m odoo_mcp.server streamable_http /path/to/config.json
```

## Verifica del Server

### Modalità stdio

```bash
# Test di una richiesta senza specificare il file di configurazione
echo '{"method": "get_resource", "params": {"uri": "odoo://res.partner/1"}}' | python -m odoo_mcp.server

# Test di una richiesta con un file di configurazione specifico
echo '{"method": "get_resource", "params": {"uri": "odoo://res.partner/1"}}' | python -m odoo_mcp.server /path/to/config.json
```

### Modalità streamable_http

```bash
# Test della connessione streamable_http
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}'
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

if __name__ == "__main__":
    asyncio.run(main())
```

### Connessione streamable_http

```python
import asyncio
from mcp import Client

async def main():
    client = Client(connection_type="streamable_http")
    await client.initialize()
    
    # Esempio: Leggi un record
    resource = await client.get_resource("odoo://res.partner/1")
    print(resource.data)

if __name__ == "__main__":
    asyncio.run(main())
```

## Documentazione

La documentazione completa è disponibile nella directory `docs/`:

- `mcp_protocol.md`: Documentazione del protocollo MCP
- `odoo_server.md`: Documentazione del server Odoo
- `server_usage.md`: Guida all'utilizzo del server

## Contribuire

1. Fork il repository
2. Crea un branch per la tua feature (`git checkout -b feature/amazing-feature`)
3. Commit le tue modifiche (`git commit -m 'Add amazing feature'`)
4. Push al branch (`git push origin feature/amazing-feature`)
5. Apri una Pull Request

## Licenza

Questo progetto è rilasciato sotto la licenza MIT. Vedi il file `LICENSE` per i dettagli.

## Aggiornamento

### Aggiornamento da Source
```bash
# Aggiorna il repository
git pull origin main

# Reinstalla il pacchetto
pip install --upgrade .

# Riavvia il server
systemctl restart odoo-mcp-server
```

### Aggiornamento con Docker
```bash
# Aggiorna le immagini
docker-compose pull

# Riavvia i container
docker-compose up -d
```

## Disinstallazione

### Disinstallazione da Source
```bash
# Disinstalla il pacchetto
pip uninstall odoo-mcp-server

# Rimuovi i file di configurazione
rm -rf ~/.odoo-mcp-server
```

### Disinstallazione con Docker
```bash
# Ferma e rimuovi i container
docker-compose down

# Rimuovi le immagini
docker-compose rm -f
```

## Configurazione Avanzata

### Configurazione per Ambienti

#### Sviluppo
```json
{
    "protocol": "xmlrpc",
    "connection_type": "stdio",
    "odoo_url": "http://localhost:8069",
    "database": "dev_db",
    "username": "admin",
    "api_key": "admin",
    "logging": {
        "level": "DEBUG",
        "handlers": [
            {
                "type": "FileHandler",
                "filename": "logs/dev.log",
                "level": "DEBUG"
            }
        ]
    }
}
```

#### Produzione
```json
{
    "protocol": "jsonrpc",
    "connection_type": "streamable_http",
    "odoo_url": "https://odoo.example.com",
    "database": "prod_db",
    "username": "admin",
    "api_key": "your-secure-api-key",
    "http": {
        "host": "0.0.0.0",
        "port": 8080,
        "streamable": true
    },
    "logging": {
        "level": "INFO",
        "handlers": [
            {
                "type": "FileHandler",
                "filename": "logs/prod.log",
                "level": "INFO"
            }
        ]
    }
}
```

### Backup della Configurazione
```bash
# Backup configurazione
cp odoo_mcp/config/config.json odoo_mcp/config/config.json.backup

# Ripristino configurazione
cp odoo_mcp/config/config.json.backup odoo_mcp/config/config.json
```

## Utilizzo Avanzato

### Gestione degli Errori
```python
from odoo_mcp.error_handling.exceptions import (
    AuthError, NetworkError, ProtocolError
)

try:
    await client.get_resource("odoo://res.partner/1")
except AuthError as e:
    logger.error(f"Errore di autenticazione: {e}")
    # Gestione errore
except NetworkError as e:
    logger.error(f"Errore di rete: {e}")
    # Gestione errore
except ProtocolError as e:
    logger.error(f"Errore di protocollo: {e}")
    # Gestione errore
```

### Best Practices

1. **Gestione delle Connessioni**:
   ```python
   async with Client() as client:
       await client.initialize()
       # Operazioni
   ```

2. **Gestione della Cache**:
   ```python
   # Configurazione cache
   cache_config = {
       'enabled': True,
       'ttl': 300,
       'max_size': 1000
   }
   ```

3. **Gestione delle Sessioni**:
   ```python
   # Creazione sessione
   session = await client.create_session()
   
   # Validazione sessione
   if await client.validate_session(session_id):
       # Operazioni
   ```

## Troubleshooting

### Problemi Comuni

1. **Errore di Connessione**:
   ```
   ERROR: Could not connect to Odoo server
   ```
   Soluzione:
   - Verifica che Odoo sia in esecuzione
   - Controlla le impostazioni di rete
   - Verifica le credenziali

2. **Errore di Autenticazione**:
   ```
   ERROR: Authentication failed
   ```
   Soluzione:
   - Verifica username e password
   - Controlla i permessi utente
   - Verifica la configurazione del database

3. **Errore di Protocollo**:
   ```
   ERROR: Protocol error
   ```
   Soluzione:
   - Verifica la versione del protocollo
   - Controlla la configurazione
   - Verifica la compatibilità

### Log di Errore

I log sono disponibili in:
- `/var/log/odoo-mcp-server/` (Linux)
- `C:\ProgramData\odoo-mcp-server\logs\` (Windows)

### Supporto

Per supporto tecnico:
1. Controlla la [documentazione](docs/)
2. Apri una [issue](https://github.com/pandeussilvae/mcp-odoo-panda/issues)
3. Contatta [support@techlab.it](mailto:support@techlab.it)

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
  - Required modules: base, web, bus
  - Database configuration with admin user
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
cp odoo_mcp/config/config.example.json odoo_mcp/config/config.json

# Modify config.json with your settings
# nano odoo_mcp/config/config.json
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

The server can be configured through a JSON file. There are different configuration templates available:

- `config.example.json`: Main template to copy and modify
- `config.dev.json`: Template for development environment (optional)
- `config.prod.json`: Template for production environment (optional)

To start:

```bash
# Copy example configuration file
cp odoo_mcp/config/config.example.json odoo_mcp/config/config.json

# Modify config.json with your settings
# nano odoo_mcp/config/config.json
```

Example of complete configuration:

```json
{
    "mcpServers": {
        "mcp-odoo-panda": {
            "command": "/usr/bin/python3",
            "args": [
                "--directory",
                "/path/to/mcp-odoo-panda",
                "mcp/server.py",
                "--config",
                "/path/to/mcp-odoo-panda/odoo_mcp/config/config.json"
            ]
        }
    },
    "odoo_url": "http://localhost:8069",
    "database": "my_database",
    "username": "admin",
    "api_key": "admin",
    "protocol": "xmlrpc",
    "connection_type": "stdio",
    "requests_per_minute": 120,
    "rate_limit_max_wait_seconds": 5,
    "pool_size": 5,
    "timeout": 30,
    "session_timeout_minutes": 60,
    "http": {
        "host": "0.0.0.0",
        "port": 8080,
        "streamable": false
    },
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        "handlers": [
            {
                "type": "StreamHandler",
                "level": "INFO"
            },
            {
                "type": "FileHandler",
                "filename": "server.log",
                "level": "DEBUG"
            }
        ]
    }
}
```

## Server Startup

Il server può essere avviato in two modes: stdio (default) and streamable_http. The configuration file is optional and, if not specified, the server will automatically look for the file in `odoo_mcp/config/config.json`.

### Modalità stdio (default)

```bash
# Avvia il server in modalità stdio senza specificare il file di configurazione
python -m odoo_mcp.server

# Avvia il server in modalità stdio con un file di configurazione specifico
python -m odoo_mcp.server /path/to/config.json
```

### Modalità streamable_http

```bash
# Avvia il server in modalità streamable_http senza specificare il file di configurazione
python -m odoo_mcp.server streamable_http

# Avvia il server in modalità streamable_http con un file di configurazione specifico
python -m odoo_mcp.server streamable_http /path/to/config.json
```

## Server Verification

### Modalità stdio

```bash
# Test di una richiesta senza specificare il file di configurazione
echo '{"method": "get_resource", "params": {"uri": "odoo://res.partner/1"}}' | python -m odoo_mcp.server

# Test di una richiesta con un file di configurazione specifico
echo '{"method": "get_resource", "params": {"uri": "odoo://res.partner/1"}}' | python -m odoo_mcp.server /path/to/config.json
```

### Modalità streamable_http

```bash
# Test della connessione streamable_http
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}'
```

## Usage

### stdio Connection

```