# Documentazione delle Classi MCP

## Classi Core

### OdooMCPServer

```python
class OdooMCPServer(Server):
    """
    Implementazione del server MCP per Odoo.
    
    Questa classe fornisce l'implementazione principale del server MCP per l'integrazione con Odoo.
    Gestisce le connessioni, le risorse, gli strumenti e i prompt per l'interazione con Odoo.
    
    Args:
        config (Dict[str, Any]): Configurazione del server
            - protocol (str): Protocollo Odoo ('xmlrpc' o 'jsonrpc')
            - connection_type (str): Tipo di connessione MCP ('stdio' o 'sse')
            - odoo_url (str): URL del server Odoo
            - database (str): Nome del database
            - uid (str): ID utente
            - password (str): Password utente
            - requests_per_minute (int): Limite di richieste al minuto
            - cache_ttl (int): Time-to-live della cache in secondi
            - allowed_origins (List[str]): Origini CORS consentite per SSE
    
    Attributes:
        protocol_handler (ProtocolHandler): Gestore del protocollo MCP
        capabilities_manager (CapabilitiesManager): Gestore delle capacità del server
        resource_manager (ResourceManager): Gestore delle risorse
        pool (ConnectionPool): Pool di connessioni Odoo
        authenticator (OdooAuthenticator): Gestore dell'autenticazione
        session_manager (SessionManager): Gestore delle sessioni
        rate_limiter (RateLimiter): Gestore del rate limiting
        bus_handler (OdooBusHandler): Gestore degli eventi bus Odoo
    """
```

### CapabilitiesManager

```python
class CapabilitiesManager:
    """
    Gestisce le capacità e i flag delle funzionalità del server.
    
    Questa classe è responsabile della gestione delle capacità del server, inclusi
    i template delle risorse, gli strumenti e i prompt disponibili.
    
    Args:
        config (Dict[str, Any]): Configurazione del gestore delle capacità
    
    Attributes:
        resources (Dict[str, ResourceTemplate]): Template delle risorse registrate
        tools (Dict[str, Tool]): Strumenti registrati
        prompts (Dict[str, Prompt]): Prompt registrati
        feature_flags (Dict[str, bool]): Flag delle funzionalità
    """
```

### ResourceManager

```python
class ResourceManager:
    """
    Gestisce le risorse del server MCP.
    
    Questa classe fornisce una gestione centralizzata delle risorse, inclusa la
    cache, la validazione e il routing delle richieste di risorse.
    
    Args:
        cache_ttl (int): Time-to-live della cache in secondi
    
    Attributes:
        _resource_cache (Dict[str, Resource]): Cache delle risorse
        _resource_handlers (Dict[str, Callable]): Handler delle risorse registrati
        _subscribers (Dict[str, Set[Callable]]): Sottoscrittori agli aggiornamenti
    """
```

### ProtocolHandler

```python
class ProtocolHandler:
    """
    Gestisce il protocollo di comunicazione MCP.
    
    Questa classe gestisce la comunicazione JSON-RPC 2.0, inclusa la validazione
    delle richieste e la formattazione delle risposte.
    
    Args:
        protocol_version (str): Versione del protocollo MCP
    
    Attributes:
        protocol_version (str): Versione del protocollo supportata
    """
```

### OdooBusHandler

```python
class OdooBusHandler:
    """
    Gestisce gli aggiornamenti in tempo reale dal sistema bus di Odoo.
    
    Questa classe gestisce la connessione WebSocket con il sistema bus di Odoo
    per ricevere aggiornamenti in tempo reale sulle risorse.
    
    Args:
        config (Dict[str, Any]): Configurazione del gestore bus
        notify_callback (Callable): Callback per le notifiche di aggiornamento
    
    Attributes:
        ws_url (str): URL WebSocket del bus Odoo
        channels (Set[str]): Canali sottoscritti
        websocket (WebSocketClientProtocol): Connessione WebSocket
        _running (bool): Stato di esecuzione
        _task (Task): Task asincrono di gestione
    """
```

### JSONRPCHandler

```python
class JSONRPCHandler:
    """
    Gestisce la comunicazione con Odoo usando il protocollo JSON-RPC.
    
    Questa classe gestisce le chiamate RPC asincrone a Odoo usando il protocollo
    JSON-RPC, inclusa la gestione della cache per le operazioni di lettura.
    
    Args:
        config (Dict[str, Any]): Configurazione del gestore
            - odoo_url (str): URL del server Odoo
            - database (str): Nome del database
            - tls_version (str, optional): Versione TLS
            - ca_cert_path (str, optional): Percorso certificato CA
            - client_cert_path (str, optional): Percorso certificato client
            - client_key_path (str, optional): Percorso chiave client
    
    Attributes:
        odoo_url (str): URL base di Odoo
        jsonrpc_url (str): URL endpoint JSON-RPC
        database (str): Nome del database
    """
```

### XMLRPCHandler

```python
class XMLRPCHandler:
    """
    Gestisce la comunicazione con Odoo usando il protocollo XML-RPC.
    
    Questa classe gestisce le chiamate RPC a Odoo usando il protocollo XML-RPC,
    inclusa la gestione della cache per le operazioni di lettura.
    
    Args:
        config (Dict[str, Any]): Configurazione del gestore
            - odoo_url (str): URL del server Odoo
            - database (str): Nome del database
            - username (str): Nome utente
            - api_key (str): Chiave API
    
    Attributes:
        odoo_url (str): URL base di Odoo
        database (str): Nome del database
        username (str): Nome utente
        password (str): Chiave API
    """
```

## Tipi di Dati

### Resource

```python
@dataclass
class Resource:
    """
    Definizione di una risorsa MCP.
    
    Args:
        uri (str): URI della risorsa
        type (str): Tipo di risorsa
        content (Any): Contenuto della risorsa
        mime_type (str): Tipo MIME del contenuto
        metadata (Dict[str, Any], optional): Metadati aggiuntivi
        last_modified (datetime, optional): Data ultima modifica
        etag (str, optional): ETag per la validazione della cache
    """
```

### ResourceTemplate

```python
@dataclass
class ResourceTemplate:
    """
    Template per una risorsa MCP.
    
    Args:
        name (str): Nome del template
        type (ResourceType): Tipo di risorsa
        description (str): Descrizione del template
        operations (List[str]): Operazioni supportate
        parameters (Dict[str, Any], optional): Parametri aggiuntivi
    """
```

### Tool

```python
@dataclass
class Tool:
    """
    Definizione di uno strumento MCP.
    
    Args:
        name (str): Nome dello strumento
        description (str): Descrizione dello strumento
        operations (List[str]): Operazioni supportate
        parameters (Dict[str, Any], optional): Parametri dello strumento
        inputSchema (Dict[str, Any], optional): Schema di input JSON
    """
```

### Prompt

```python
@dataclass
class Prompt:
    """
    Definizione di un prompt MCP.
    
    Args:
        name (str): Nome del prompt
        description (str): Descrizione del prompt
        template (str): Template del prompt
        parameters (Dict[str, Any], optional): Parametri del prompt
    """
```

## Best Practices per l'Utilizzo

1. **Inizializzazione del Server**:
   ```python
   config = {
       'protocol': 'xmlrpc',
       'connection_type': 'stdio',
       'odoo_url': 'http://localhost:8069',
       'database': 'my_database',
       'uid': 'admin',
       'password': 'admin',
       'requests_per_minute': 120,
       'cache_ttl': 300
   }
   server = OdooMCPServer(config)
   ```

2. **Gestione delle Risorse**:
   ```python
   # Registrazione di un handler di risorsa
   server.resource_manager.register_resource_handler(
       "odoo://{model}/{id}",
       handler_function
   )
   
   # Recupero di una risorsa
   resource = await server.get_resource("odoo://res.partner/1")
   ```

3. **Gestione degli Eventi**:
   ```python
   # Sottoscrizione agli aggiornamenti
   await server.bus_handler.subscribe("res.partner")
   
   # Gestione degli aggiornamenti
   async def handle_update(uri, data):
       print(f"Risorsa aggiornata: {uri}")
   ```

4. **Gestione degli Errori**:
   ```python
   try:
       await server.execute_operation(...)
   except AuthError:
       # Gestione errore autenticazione
   except NetworkError:
       # Gestione errore rete
   except ProtocolError:
       # Gestione errore protocollo
   ```

5. **Configurazione della Cache**:
   ```python
   # Configurazione cache
   cache_config = {
       'enabled': True,
       'ttl': 300,
       'max_size': 1000
   }
   ```

6. **Gestione delle Sessioni**:
   ```python
   # Creazione sessione
   session = await server.session_manager.create_session()
   
   # Validazione sessione
   if await server.session_manager.validate_session(session_id):
       # Operazioni con sessione valida
   ``` 