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

### Selezione della modalità di connessione

Il server Odoo MCP supporta diverse modalità di connessione, configurabili tramite il campo `connection_type` in `config.json`. Valori supportati:

- `stdio`: Default, comunicazione diretta via stdin/stdout
- `streamable_http`: HTTP con risposte in streaming/chunked (flussi dati real-time)
- `http`: HTTP POST classico (stateless, richiesta/risposta singola)

Esempio di configurazione:
```json
{
  "connection_type": "streamable_http",  // oppure "http" o "stdio"
  "http": {
    "host": "0.0.0.0",
    "port": 8080
  }
}
```

- Usa `streamable_http` per streaming real-time su HTTP (endpoint: `POST /mcp`)
- Usa `http` per richieste REST classiche (endpoint: `POST /mcp`)
- Usa `stdio` per comunicazione diretta (default)

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
    "connection_type": "streamable_http",
    "requests_per_minute": 120,
    "rate_limit_max_wait_seconds": 5,
    "pool_size": 5,
    "timeout": 30,
    "session_timeout_minutes": 60,
    "http": {
        "host": "0.0.0.0",
        "port": 8080,
        "streamable": true
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

### Modalità HTTP

Il server Odoo MCP supporta due modalità HTTP:

1. **HTTP Streaming Chunked** (`streamable_http`):
   - Endpoint: `POST /mcp`
   - Mantiene la connessione aperta e invia dati in streaming
   - Ideale per flussi di dati in tempo reale
   - Headers richiesti:
     ```
     Content-Type: application/json
     Connection: keep-alive
     ```

2. **HTTP POST Classica** (`http`):
   - Endpoint: `POST /mcp`
   - Gestisce una singola richiesta/risposta (stateless)
   - Comportamento standard REST
   - Headers richiesti:
     ```
     Content-Type: application/json
     ```

3. **Server-Sent Events** (SSE):
   - Endpoint: `GET /sse`
   - Supporto per eventi server-push
   - Headers richiesti:
     ```
     Accept: text/event-stream
     ```

Per configurare la modalità HTTP, imposta `connection_type` in `config.json`:
```json
{
  "connection_type": "streamable_http",  // o "http"
  "http": {
    "host": "0.0.0.0",
    "port": 8080
  }
}
```

### Esempi di Chiamata

1. **HTTP Streaming Chunked**:
```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Connection: keep-alive" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "id": 1}'
```

2. **HTTP POST Classica**:
```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "id": 1}'
```

3. **Server-Sent Events**:
```bash
curl -N http://localhost:8080/sse \
  -H "Accept: text/event-stream"
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
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Connection: keep-alive" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}'
```

### Modalità http (Classic HTTP POST)

```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}'
```

### Modalità Server-Sent Events (SSE)

```bash
curl -N http://localhost:8080/sse \
  -H "Accept: text/event-stream"
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