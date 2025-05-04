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

### Connessione di Claude Desktop al server Odoo MCP (stdio)

Per collegare Claude Desktop al server Odoo MCP tramite protocollo stdio:

1. Assicurati che il server Odoo MCP sia installato e funzionante.
2. Apri le impostazioni di Claude Desktop (menu Claude → Settings → Developer → Edit Config).
3. Inserisci la seguente configurazione nella sezione `mcpServers` del file `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "odoo-mcp": {
      "command": "python",
      "args": [
        "-m",
        "odoo_mcp.server",
        "C:/percorso/assoluto/al/tuo/config.json"
      ]
    }
  }
}
```
> Sostituisci `C:/percorso/assoluto/al/tuo/config.json` con il percorso reale del tuo file di configurazione.

4. Salva e riavvia Claude Desktop. Dovresti vedere gli strumenti MCP disponibili.

**Nota:** Claude Desktop comunica solo tramite stdio. Non usare `streamable_http` per la connessione con Claude Desktop.

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
   - Verifica che Odoo sia in esecuzione sulla porta 8069
   - Controlla che il firewall permetta l'accesso alla porta 8069
   - Verifica che l'URL di Odoo nel file di configurazione sia corretto
   - Controlla che il database sia accessibile

2. **Errore di Autenticazione**:
   ```
   ERROR: Authentication failed
   ```
   Soluzione:
   - Verifica che username e api_key nel file di configurazione siano corretti
   - Controlla che l'utente abbia i permessi necessari nel database Odoo
   - Verifica che il database specificato esista
   - Controlla che i moduli base, web e bus siano installati

3. **Errore di Protocollo**:
   ```
   ERROR: Protocol error
   ```
   Soluzione:
   - Verifica che il protocollo specificato (xmlrpc/jsonrpc) sia supportato
   - Controlla che la versione di Odoo sia compatibile (15.0+)
   - Verifica che il tipo di connessione (stdio/streamable_http) sia corretto
   - Controlla i log per dettagli specifici sull'errore

4. **Errore di Rate Limiting**:
   ```
   ERROR: Rate limit exceeded
   ```
   Soluzione:
   - Aumenta il valore di `requests_per_minute` nel file di configurazione
   - Implementa un meccanismo di retry con backoff
   - Ottimizza le richieste per ridurre il numero di chiamate

5. **Errore di Cache**:
   ```
   ERROR: Cache error
   ```
   Soluzione:
   - Verifica che il tipo di cache configurato sia supportato
   - Controlla che ci sia spazio sufficiente per la cache
   - Disabilita temporaneamente la cache se necessario

### Log di Errore

**Nota importante:** Nella versione attuale, il server Odoo MCP può scrivere i log in più destinazioni a seconda della configurazione:

- Se nella sezione `logging` di `config.json` è presente un handler di tipo `StreamHandler`, i log vengono scritti sulla **console** (stderr).
- Se è presente un handler di tipo `FileHandler`, i log vengono scritti anche su **file** nel percorso specificato dal campo `filename`.
- Se non esiste la sezione `logging`, i log vengono scritti solo su stderr (console).

**Esempio:**
```json
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
```
- In questo esempio, i log vanno sia sulla console che nel file `server.log` nella cartella da cui avvii il server.
- Puoi cambiare il percorso del file modificando il campo `filename` (es: `"filename": "logs/dev.log"` o un percorso assoluto).

### Supporto

Per supporto tecnico:
1. Controlla la [documentazione](docs/)
2. Apri una [issue](https://github.com/pandeussilvae/mcp-odoo-panda/issues)
3. Contatta [support@techlab.it](mailto:support@techlab.it)

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

The server can be started in two modes: stdio (default) and streamable_http. The configuration file is optional and, if not specified, the server will automatically look for the file in `odoo_mcp/config/config.json`.

### stdio Mode (default)

```bash
# Start the server in stdio mode without specifying the configuration file
python -m odoo_mcp.server

# Start the server in stdio mode with a specific configuration file
python -m odoo_mcp.server /path/to/config.json
```

### streamable_http Mode

```bash
# Start the server in streamable_http mode without specifying the configuration file
python -m odoo_mcp.server streamable_http

# Start the server in streamable_http mode with a specific configuration file
python -m odoo_mcp.server streamable_http /path/to/config.json
```

## Server Verification

### stdio Mode

```bash
# Test a request without specifying the configuration file
echo '{"method": "get_resource", "params": {"uri": "odoo://res.partner/1"}}' | python -m odoo_mcp.server

# Test a request with a specific configuration file
echo '{"method": "get_resource", "params": {"uri": "odoo://res.partner/1"}}' | python -m odoo_mcp.server /path/to/config.json
```

### streamable_http Mode

```bash
# Test streamable_http connection
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}'
```

## Usage

### stdio Connection

```python
import asyncio
from mcp import Client

async def main():
    client = Client(connection_type="stdio")
    await client.initialize()
    
    # Example: Read a record
    resource = await client.get_resource("odoo://res.partner/1")
    print(resource.data)

if __name__ == "__main__":
    asyncio.run(main())
```

### streamable_http Connection

```python
import asyncio
from mcp import Client

async def main():
    client = Client(connection_type="streamable_http")
    await client.initialize()
    
    # Example: Read a record
    resource = await client.get_resource("odoo://res.partner/1")
    print(resource.data)

if __name__ == "__main__":
    asyncio.run(main())
```

### Connecting Claude Desktop to the Odoo MCP server (stdio)

To connect Claude Desktop to the Odoo MCP server using the stdio protocol:

1. Make sure the Odoo MCP server is installed and working.
2. Open Claude Desktop settings (Claude menu → Settings → Developer → Edit Config).
3. Add the following configuration to the `mcpServers` section of your `claude_desktop_config.json` file:

```json
{
  "mcpServers": {
    "odoo-mcp": {
      "command": "python",
      "args": [
        "-m",
        "odoo_mcp.server",
        "C:/absolute/path/to/your/config.json"
      ]
    }
  }
}
```
> Replace `C:/absolute/path/to/your/config.json` with the actual path to your configuration file.

4. Save and restart Claude Desktop. You should see the MCP tools available.

**Note:** Claude Desktop only communicates via stdio. Do not use `streamable_http` for connecting with Claude Desktop.

## Documentation

Complete documentation is available in the `docs/` directory:

- `mcp_protocol.md`: MCP protocol documentation
- `odoo_server.md`: Odoo server documentation
- `server_usage.md`: Server usage guide

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is released under the MIT License. See the `LICENSE` file for details.

## Update

### Update from Source
```bash
# Update repository
git pull origin main

# Reinstall package
pip install --upgrade .

# Restart server
systemctl restart odoo-mcp-server
```

### Update with Docker
```bash
# Update images
docker-compose pull

# Restart containers
docker-compose up -d
```

## Uninstallation

### Uninstall from Source
```bash
# Uninstall package
pip uninstall odoo-mcp-server

# Remove configuration files
rm -rf ~/.odoo-mcp-server
```

### Uninstall with Docker
```bash
# Stop and remove containers
docker-compose down

# Remove images
docker-compose rm -f
```

## Advanced Configuration

### Environment Configuration

#### Development
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

#### Production
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

### Configuration Backup
```bash
# Backup configuration
cp odoo_mcp/config/config.json odoo_mcp/config/config.json.backup

# Restore configuration
cp odoo_mcp/config/config.json.backup odoo_mcp/config/config.json
```

## Advanced Usage

### Error Handling
```python
from odoo_mcp.error_handling.exceptions import (
    AuthError, NetworkError, ProtocolError
)

try:
    await client.get_resource("odoo://res.partner/1")
except AuthError as e:
    logger.error(f"Authentication error: {e}")
    # Error handling
except NetworkError as e:
    logger.error(f"Network error: {e}")
    # Error handling
except ProtocolError as e:
    logger.error(f"Protocol error: {e}")
    # Error handling
```

### Best Practices

1. **Connection Management**:
   ```python
   async with Client() as client:
       await client.initialize()
       # Operations
   ```

2. **Cache Management**:
   ```python
   # Cache configuration
   cache_config = {
       'enabled': True,
       'ttl': 300,
       'max_size': 1000
   }
   ```

3. **Session Management**:
   ```python
   # Create session
   session = await client.create_session()
   
   # Validate session
   if await client.validate_session(session_id):
       # Operations
   ```

## Troubleshooting

### Common Issues

1. **Connection Error**:
   ```
   ERROR: Could not connect to Odoo server
   ```
   Solution:
   - Verify that Odoo is running on port 8069
   - Check that the firewall allows access to port 8069
   - Verify that the Odoo URL in the configuration file is correct
   - Check that the database is accessible

2. **Authentication Error**:
   ```
   ERROR: Authentication failed
   ```
   Solution:
   - Verify that username and api_key in the configuration file are correct
   - Check that the user has the necessary permissions in the Odoo database
   - Verify that the specified database exists
   - Check that the base, web, and bus modules are installed

3. **Protocol Error**:
   ```
   ERROR: Protocol error
   ```
   Solution:
   - Verify that the specified protocol (xmlrpc/jsonrpc) is supported
   - Check that the Odoo version is compatible (15.0+)
   - Verify that the connection type (stdio/streamable_http) is correct
   - Check the logs for specific error details

4. **Rate Limiting Error**:
   ```
   ERROR: Rate limit exceeded
   ```
   Solution:
   - Increase the `requests_per_minute` value in the configuration file
   - Implement a retry mechanism with backoff
   - Optimize requests to reduce the number of calls

5. **Cache Error**:
   ```
   ERROR: Cache error
   ```
   Solution:
   - Verify that the configured cache type is supported
   - Check that there is sufficient space for the cache
   - Temporarily disable the cache if necessary

### Error Logs

**Important note:** In the current version, the Odoo MCP server can write logs to multiple destinations depending on configuration:

- If the `logging` section in `config.json` includes a `StreamHandler`, logs are written to the **console** (stderr).
- If a `FileHandler` is present, logs are also written to a **file** at the path specified by `filename`.
- If there is no `logging` section, logs are written only to stderr (console).

**Example:**
```json
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
```
- In this example, logs go both to the console and to the file `server.log` in the directory where you start the server.
- You can change the log file path by editing the `filename` field (e.g., `"filename": "logs/dev.log"` or an absolute path).

### Support

For technical support:
1. Check the [documentation](docs/)
2. Open an [issue](https://github.com/pandeussilvae/mcp-odoo-panda/issues)
3. Contact [support@techlab.it](mailto:support@techlab.it)

