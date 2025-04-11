# Odoo MCP Server (mcp-odoo-panda)

## Descrizione

Questo progetto implementa un server Message Control Program (MCP) progettato per facilitare l'integrazione e l'interazione con istanze Odoo ERP. Fornisce un'interfaccia standardizzata (JSON-RPC o XML-RPC) per eseguire operazioni su Odoo, gestendo connessioni, autenticazione e sessioni.

## Funzionalità Principali Attuali

*   **Protocolli Multipli:** Supporto per comunicare con Odoo tramite **XML-RPC** (protocollo standard di Odoo) e **JSON-RPC**.
*   **Pool di Connessioni Asincrono:** Gestisce un pool di connessioni riutilizzabili verso Odoo per migliorare le prestazioni e ridurre l'overhead, utilizzando `httpx` per le chiamate asincrone (nel caso di JSON-RPC) e la libreria standard `xmlrpc.client` (adattata per l'uso asincrono).
*   **Autenticazione:** Supporta l'autenticazione degli utenti tramite username/password o API key forniti nella configurazione o per sessione.
*   **Gestione Sessioni:** Crea e gestisce sessioni utente con un tempo di scadenza configurabile e un task di pulizia automatica per le sessioni scadute.
*   **Rate Limiting:** Limita il numero di richieste al secondo per prevenire sovraccarichi, configurabile tramite file.
*   **Modalità di Comunicazione:**
    *   **stdio:** Il server comunica tramite standard input/output, ricevendo richieste JSON-RPC su stdin e inviando risposte su stdout.
    *   **SSE (Server-Sent Events):** (Implementazione di base presente) Utilizza `aiohttp` per esporre un endpoint `/events` per lo streaming delle risposte e un endpoint `/mcp` per ricevere richieste POST. Richiede test e potenziali miglioramenti.
*   **Configurazione Flessibile:** Utilizza file YAML (`config.dev.yaml`, `config.prod.yaml`) per configurare parametri come URL di Odoo, database, credenziali, dimensioni del pool, timeout, rate limit (incluso timeout di attesa), protocollo, caching (TTL, maxsize), ecc.
*   **Logging Configurabile:** Sistema di logging integrato configurabile tramite il file YAML per diversi livelli e output.
*   **Gestione Errori:** Definisce eccezioni personalizzate per errori comuni (configurazione, protocollo, autenticazione, rete). Mappa gli errori specifici restituiti da Odoo (es. errori di validazione, permessi, record non trovato) a eccezioni dedicate (`OdooValidationError`, `OdooRecordNotFoundError`, `AuthError`) per una gestione più granulare.
*   **Validazione Input:** Utilizza Pydantic per validare la struttura e i tipi dei parametri per ciascun metodo API, restituendo errori JSON-RPC specifici (`-32602 Invalid params`) in caso di fallimento.
*   **Struttura Modulare:** Codice organizzato in moduli specifici (authentication, connection, core, error_handling, performance, security).
*   **Packaging:** Configurato come pacchetto Python standard tramite `pyproject.toml`.
*   **Testing:** Include una suite di test (`pytest`) per diverse componenti (anche se la copertura completa non è garantita).

## Installazione

```bash
# Clona il repository (se non già fatto)
# git clone <repository-url>
# cd mcp-odoo-panda

# Crea e attiva un ambiente virtuale (consigliato)
python -m venv venv
source venv/bin/activate # Su Linux/macOS
# venv\Scripts\activate # Su Windows

# Installa il pacchetto e le dipendenze di sviluppo
pip install -e .[dev]

# Installa anche le dipendenze per il caching se necessario
pip install -e .[caching]
```

## Configurazione

Il server viene configurato tramite file YAML presenti nella directory `odoo_mcp/config/`.

*   `config.dev.yaml`: Configurazione per l'ambiente di sviluppo.
*   `config.prod.yaml`: Configurazione per l'ambiente di produzione.

È possibile specificare il file di configurazione da usare all'avvio del server. I parametri principali includono:

*   `odoo_url`: URL dell'istanza Odoo.
*   `database`: Nome del database Odoo.
*   `username`/`password` o `api_key`: Credenziali globali (usate se non specificate nella richiesta).
*   `protocol`: `xmlrpc` o `jsonrpc`.
*   `connection_type`: `stdio` o `sse`.
*   `pool_size`: Numero massimo di connessioni nel pool.
*   `timeout`: Timeout per le richieste a Odoo.
*   `requests_per_minute`: Limite per il rate limiter (token/minuto).
*   `rate_limit_max_wait_seconds` (opzionale): Tempo massimo in secondi di attesa se il rate limit viene superato.
*   `session_timeout_minutes`: Durata delle sessioni utente.
*   `logging`: Configurazione del logger (livello, formato, handler).
*   `cache`: Impostazioni per il caching TTL (se `cachetools` è installato):
    *   `default_maxsize`: Numero massimo di elementi nella cache.
    *   `default_ttl`: Tempo di vita (in secondi) degli elementi nella cache.
*   `sse_host`/`sse_port`: Indirizzo e porta per la modalità SSE.

## Uso

Il server può essere avviato specificando il file di configurazione e la modalità di connessione desiderata (`stdio` o `sse`) all'interno del file stesso.

```bash
# Esempio di avvio usando il modulo python
python -m odoo_mcp.core.mcp_server --config odoo_mcp/config/config.dev.yaml

# Esempio di avvio usando l'entry point (se installato con 'pip install .')
odoo-mcp-server --config odoo_mcp/config/config.dev.yaml
```

**Modalità di Comunicazione:**

*   **`stdio` (Standard Input/Output):**
    *   Questa è la modalità predefinita se `connection_type` non è specificato o è impostato su `stdio` nel file di configurazione.
    *   Il server legge le richieste JSON-RPC da `stdin` (una richiesta per riga) e scrive le risposte JSON-RPC su `stdout` (una risposta per riga).
    *   Adatto per l'integrazione con altri processi o script.

*   **`sse` (Server-Sent Events):**
    *   Attivata impostando `connection_type: sse` nel file di configurazione.
    *   Il server avvia un server HTTP `aiohttp` (configurabile tramite `sse_host` e `sse_port`).
    *   **Endpoint `/mcp` (POST):** I client inviano le loro richieste JSON-RPC come corpo JSON a questo endpoint. Il server risponde immediatamente con `202 Accepted`.
    *   **Endpoint `/events` (GET):** I client stabiliscono una connessione SSE a questo endpoint. Il server invierà le *risposte* alle richieste ricevute su `/mcp` come eventi SSE a *tutti* i client connessi a `/events`.
    *   Utile per scenari web o client che necessitano di ricevere aggiornamenti asincroni.

**Esempio Richiesta (JSON-RPC):**

Il formato della richiesta è lo stesso per entrambe le modalità:

```json
{"jsonrpc": "2.0", "method": "call_odoo", "params": {"model": "res.partner", "method": "search_count", "args": [[["is_company", "=", true]]]}, "id": 1}
```

Consultare `odoo_mcp/examples/basic_usage.py` per un esempio di client base (orientato a stdio).

**Metodi API Disponibili:**

*   `echo`: Restituisce il messaggio inviato (per test).
*   `create_session`: Crea una nuova sessione utente fornendo `username` e `api_key`. Restituisce `session_id` e `user_id`.
*   `destroy_session`: Invalida una sessione esistente fornendo `session_id`.
*   `call_odoo`: Esegue un metodo su un modello Odoo. Richiede:
    *   `model`: Nome del modello Odoo (es. `res.partner`).
    *   `method`: Nome del metodo da chiamare (es. `search_read`).
    *   `args`: Lista di argomenti posizionali per il metodo Odoo.
    *   `kwargs`: Dizionario di argomenti keyword per il metodo Odoo.
    *   `session_id` (opzionale): ID della sessione da usare per l'autenticazione.
    *   `uid`/`password` (opzionale): Credenziali specifiche per questa chiamata (usate se `session_id` non è fornito e si vogliono sovrascrivere quelle globali).

**Esempio Richiesta (stdio):**

```json
{"jsonrpc": "2.0", "method": "call_odoo", "params": {"model": "res.partner", "method": "search_count", "args": [[["is_company", "=", true]]]}, "id": 1}
```

Consultare `odoo_mcp/examples/basic_usage.py` per un esempio di client base.

## Architettura

Il server è composto dai seguenti moduli principali:

*   **`core`**: Contiene la logica principale del server (`mcp_server.py`), gli handler per i protocolli RPC (`xmlrpc_handler.py`, `jsonrpc_handler.py`) e la configurazione del logging (`logging_config.py`).
*   **`connection`**: Gestisce la comunicazione con Odoo, includendo il pool di connessioni (`connection_pool.py`) e la gestione delle sessioni (`session_manager.py`).
*   **`authentication`**: Si occupa dell'autenticazione degli utenti (`authenticator.py`).
*   **`security`**: Implementa funzionalità di sicurezza come il rate limiting e utility per la validazione/mascheramento dati (`utils.py`).
*   **`error_handling`**: Definisce le eccezioni personalizzate (`exceptions.py`).
*   **`performance`**: Contiene logica per ottimizzazioni come il caching (`caching.py`).
*   **`config`**: File di configurazione YAML.
*   **`examples`**: Codice di esempio per l'utilizzo del server.
*   **`tests`**: Test unitari e di integrazione.

## TODO / Roadmap Futura

*   **Documentazione:**
    *   Migliorare README (esempi complessi, best practice).
    *   Aggiungere docstring dettagliate alle classi/metodi rimanenti.
    *   Creare documentazione architetturale formale.
*   **Testing:**
    *   Aumentare copertura test unitari/integrazione.
    *   Aggiungere test specifici per: Errori HTTP JSON-RPC, Health check pool, Pulizia sessioni, Modalità SSE, Validazione Input, Mappatura Errori.
*   **Caching:**
    *   Valutare caching per altri tipi di dati/metodi Odoo.
    *   **Nota Sicurezza:** Evitare di memorizzare direttamente credenziali o token di sessione nella cache per motivi di sicurezza (TODO completato tramite nota).
*   **Autenticazione/Sessioni:**
    *   Implementare verifica/generazione sicura token di sessione (se si sceglie approccio token).
    *   **Nota:** La logica attuale per `call_odoo` con `session_id` usa un fallback alla chiave globale (necessario per `execute_kw` standard). Una soluzione più robusta è rimandata (TODO parzialmente completato con chiarimenti).
*   **Modalità SSE:**
    *   Rendere più robusta e testare approfonditamente.
*   **Esempi:**
    *   Fornire esempi d'uso più complessi.
*   **CI/CD:**
    *   Implementare pipeline CI/CD.

## Licenza

(Licenza MIT confermata nel file `LICENSE`)

Questo progetto è rilasciato sotto la licenza MIT. Vedere il file `LICENSE` per i dettagli.
