# MCP Server Configuration / Configurazione MCP Server

[English](#english) | [Italiano](#italiano)

<a name="english"></a>
# MCP Server Configuration

This document describes all available parameters in the `config.json` configuration file.

## Odoo Connection Configuration

- `odoo_url`: Odoo server URL (e.g., "http://localhost:8069")
- `database`: Odoo database name
- `username`: Authentication username
- `api_key`: Authentication API key

## Protocol and Connection Configuration

- `protocol`: Odoo communication protocol
  - Possible values: "xmlrpc" or "jsonrpc"
  - Default: "xmlrpc"
- `connection_type`: MCP server connection type
  - Possible values: "stdio" or "sse"
  - Default: "stdio"

## Rate Limiting Configuration

- `requests_per_minute`: Maximum number of requests per minute
  - Default: 120
- `rate_limit_max_wait_seconds`: Maximum wait time for queued requests
  - Default: 5

## Connection Pool Configuration

- `pool_size`: Maximum number of connections in the pool
  - Default: 5
- `timeout`: Request timeout in seconds
  - Default: 30
- `session_timeout_minutes`: Maximum session duration in minutes
  - Default: 60

## HTTP Configuration

- `http.host`: Host the server listens on
  - Default: "0.0.0.0"
- `http.port`: Port the server listens on
  - Default: 8080
- `http.streamable`: Enable/disable response streaming
  - Default: false

## Logging Configuration

- `logging.level`: Log level
  - Possible values: "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
  - Default: "INFO"
- `logging.format`: Log message format
  - Default: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
- `logging.handlers`: List of log handlers
  - `StreamHandler`: Console output
    - `level`: Console log level
  - `FileHandler`: File output
    - `filename`: Log file name
    - `level`: File log level

## Notes

- All parameters are optional and have default values
- Example values in the configuration file are for a local development environment
- For a production environment, ensure to:
  1. Use secure credentials
  2. Configure appropriate timeouts and rate limits
  3. Set appropriate log levels
  4. Configure the correct HTTP host and port

---

<a name="italiano"></a>
# Configurazione MCP Server

Questo documento descrive tutti i parametri disponibili nel file di configurazione `config.json`.

## Configurazione Connessione Odoo

- `odoo_url`: URL del server Odoo (es. "http://localhost:8069")
- `database`: Nome del database Odoo
- `username`: Username per l'autenticazione
- `api_key`: Chiave API per l'autenticazione

## Configurazione Protocollo e Connessione

- `protocol`: Protocollo di comunicazione con Odoo
  - Valori possibili: "xmlrpc" o "jsonrpc"
  - Default: "xmlrpc"
- `connection_type`: Tipo di connessione per il server MCP
  - Valori possibili: "stdio" o "sse"
  - Default: "stdio"

## Configurazione Rate Limiting

- `requests_per_minute`: Numero massimo di richieste al minuto
  - Default: 120
- `rate_limit_max_wait_seconds`: Tempo massimo di attesa per le richieste in coda
  - Default: 5

## Configurazione Pool Connessioni

- `pool_size`: Numero massimo di connessioni nel pool
  - Default: 5
- `timeout`: Timeout in secondi per le richieste
  - Default: 30
- `session_timeout_minutes`: Durata massima della sessione in minuti
  - Default: 60

## Configurazione HTTP

- `http.host`: Host su cui il server ascolta
  - Default: "0.0.0.0"
- `http.port`: Porta su cui il server ascolta
  - Default: 8080
- `http.streamable`: Abilita/disabilita lo streaming delle risposte
  - Default: false

## Configurazione Logging

- `logging.level`: Livello di log
  - Valori possibili: "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
  - Default: "INFO"
- `logging.format`: Formato dei messaggi di log
  - Default: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
- `logging.handlers`: Lista degli handler di log
  - `StreamHandler`: Output su console
    - `level`: Livello di log per la console
  - `FileHandler`: Output su file
    - `filename`: Nome del file di log
    - `level`: Livello di log per il file

## Note

- Tutti i parametri sono opzionali e hanno valori predefiniti
- I valori di esempio nel file di configurazione sono per un ambiente di sviluppo locale
- Per un ambiente di produzione, assicurarsi di:
  1. Utilizzare credenziali sicure
  2. Configurare correttamente i timeout e i limiti di rate
  3. Impostare livelli di log appropriati
  4. Configurare correttamente l'host e la porta HTTP 