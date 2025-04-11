<div align="center">
  <img src="assets/Odoo MCP Server.png" alt="Odoo MCP Server Logo" width="100%"/> 
</div>
<br/>

# Odoo MCP Server (mcp-odoo-panda)

## 📝 Descrizione

Questo progetto implementa un server Message Control Program (MCP) progettato per facilitare l'integrazione e l'interazione con istanze Odoo ERP. Fornisce un'interfaccia standardizzata (JSON-RPC o XML-RPC) per eseguire operazioni su Odoo, gestendo connessioni, autenticazione e sessioni.

## ✨ Funzionalità Principali Attuali

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
*   **Conformità MCP:** Implementa le primitive standard del Model Context Protocol:
    *   **Tools:** Espone funzionalità Odoo tramite `list_tools` e `call_tool`. Include tool specifici per operazioni CRUD (`odoo_search_read`, `odoo_read`, `odoo_create`, `odoo_write`, `odoo_unlink`) e chiamate a metodi generici (`odoo_call_method`), oltre a tool di base (`echo`, `create_session`, `destroy_session`).
    *   **Resources:** Permette l'accesso ai record Odoo come risorse tramite `list_resource_templates` (con template `odoo://{model}/{id}`) e `read_resource`.
*   **Validazione Input:** La validazione dei parametri per i tool e le risorse MCP è gestita internamente alla logica dei rispettivi metodi standard (`call_tool`, `read_resource`).
*   **Struttura Modulare:** Codice organizzato in moduli specifici (authentication, connection, core, error_handling, performance, security).
*   **Packaging:** Configurato come pacchetto Python standard tramite `pyproject.toml`.
*   **Testing:** Include una suite di test (`pytest`) per diverse componenti (anche se la copertura completa non è garantita).

## 🚀 Installazione

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

## 🔧 Configurazione

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

## ▶️ Uso

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

Consultare `odoo_mcp/examples/basic_usage.py` per un esempio di client base (potrebbe necessitare di aggiornamento per usare i tool MCP).

**🔌 Interfaccia MCP:**

Il server ora espone le seguenti primitive standard MCP:

*   **`list_tools`**:
    *   **Parametri:** Nessuno.
    *   **Risposta:** Un oggetto JSON contenente una lista `tools`. Ogni tool ha `name`, `description`, e `inputSchema` (JSON Schema che descrive i parametri attesi nel campo `arguments` di `call_tool`).
    *   **Tool Disponibili:**
        *   `echo`: Restituisce il messaggio fornito.
        *   `create_session`: Crea una sessione Odoo.
        *   `destroy_session`: Distrugge una sessione Odoo.
        *   `odoo_search_read`: Cerca record Odoo con dominio e campi specifici.
        *   `odoo_read`: Legge campi specifici per ID record dati.
        *   `odoo_create`: Crea un nuovo record Odoo.
        *   `odoo_write`: Aggiorna record Odoo esistenti.
        *   `odoo_unlink`: Elimina record Odoo.
        *   `odoo_call_method`: Chiama un metodo specifico su record Odoo.
    *   **Autenticazione per Tool Odoo:** Tutti i tool `odoo_*` richiedono l'autenticazione tramite `session_id` o `uid`/`password` all'interno dei loro `arguments`.

*   **`call_tool`**:
    *   **Parametri:** Un oggetto JSON con:
        *   `name` (string): Il nome del tool da eseguire (deve corrispondere a uno restituito da `list_tools`).
        *   `arguments` (object): Un oggetto contenente i parametri specifici per quel tool, come definito nel suo `inputSchema`.
    *   **Risposta:** Un oggetto JSON con un campo `content` (un array contenente il risultato del tool, solitamente come oggetto `{"type": "text", "text": "..."}` con il risultato JSON-encoded).

*   **`list_resource_templates`**:
    *   **Parametri:** Nessuno.
    *   **Risposta:** Un oggetto JSON contenente una lista `resourceTemplates`. Ogni template ha `uriTemplate`, `name`, `description`, `mimeType`, e `inputSchema` (che descrive i parametri necessari per `read_resource`, inclusa l'autenticazione).
    *   **Template Disponibile:**
        *   `odoo://{model}/{id}`: Rappresenta un singolo record Odoo.

*   **`read_resource`**:
    *   **Parametri:** Un oggetto JSON con:
        *   `uri` (string): L'URI specifico della risorsa da leggere (es. `odoo://res.partner/123`).
        *   `session_id` (string, opzionale): Autenticazione tramite sessione.
        *   `uid` (integer, opzionale) & `password` (string, opzionale): Autenticazione diretta.
    *   **Risposta:** Un oggetto JSON con un campo `contents` (un array contenente un oggetto con `uri`, `mimeType`, e `text` con i dati del record JSON-encoded).

**Esempio Richiesta MCP (stdio - `call_tool`):**

```json
{
  "jsonrpc": "2.0",
  "method": "call_tool",
  "params": {
    "name": "odoo_search_read",
    "arguments": {
      "model": "res.partner",
      "domain": [["is_company", "=", true]],
      "fields": ["name", "email"],
      "limit": 5,
      "session_id": "some-valid-session-id" 
    }
  },
  "id": 2
}
```

**Esempio Richiesta MCP (stdio - `read_resource`):**

```json
{
  "jsonrpc": "2.0",
  "method": "read_resource",
  "params": {
    "uri": "odoo://res.partner/123",
    "uid": 1,
    "password": "admin" 
  },
  "id": 3
}
```

## 💻 Connessione Client MCP (Modalità stdio)

I client MCP standard, come l'estensione VS Code o l'app desktop Claude, comunicano con i server MCP tramite **standard input/output (stdio)**. Per connettere un client a questo server Odoo MCP, devi configurarlo per eseguire il server Python in modalità `stdio`.

**1. Assicurati che la Configurazione del Server usi `stdio`:**

Nel file YAML di configurazione che intendi usare (es. `odoo_mcp/config/config.dev.yaml`), assicurati che il parametro `connection_type` sia impostato su `stdio` o che sia omesso (poiché `stdio` è il default):

```yaml
# Esempio in config.dev.yaml
connection_type: stdio
# ... altre configurazioni ...
```

**2. Configura il Client MCP:**

Modifica il file di configurazione del tuo client MCP (es. `/root/.vscode-server/data/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` per l'estensione VS Code in questo ambiente, o `~/Library/Application Support/Claude/claude_desktop_config.json` su macOS per l'app desktop). Aggiungi o modifica una voce sotto `mcpServers`:

```json
{
  "mcpServers": {
    "odoo-local": {
      // Percorso dell'eseguibile Python (preferibilmente dall'ambiente virtuale)
      "command": "/root/mcp-odoo-panda/mcp-odoo-panda/venv/bin/python", // Esempio: Adatta al tuo percorso venv
      "args": [
        "-m", // Esegui come modulo
        "odoo_mcp.core.mcp_server", // Percorso del modulo server
        "--config", // Argomento per specificare il file di config
        "/root/mcp-odoo-panda/mcp-odoo-panda/odoo_mcp/config/config.dev.yaml" // Percorso ASSOLUTO del file di config
      ],
      // 'env' può essere usato per passare variabili d'ambiente se il server le legge,
      // ma questo server si basa principalmente sul file YAML.
      "env": {
          // Esempio: "ODOO_PASSWORD_VAR": "secret"
      },
      "enable": true, // Abilita il server
      "autoApprove": [] // Configura l'approvazione automatica se necessario
    }
    // ... altri server MCP ...
  }
}
```

*   **`command`**: Specifica il percorso completo dell'eseguibile Python del tuo ambiente virtuale (consigliato) o il comando `python` se è nel PATH di sistema e configurato correttamente.
*   **`args`**: Contiene gli argomenti per avviare il server:
    *   `-m odoo_mcp.core.mcp_server`: Dice a Python di eseguire il modulo del server.
    *   `--config`: L'opzione per passare il file di configurazione.
    *   `/root/mcp-odoo-panda/mcp-odoo-panda/odoo_mcp/config/config.dev.yaml`: **Percorso assoluto** del file di configurazione YAML che vuoi usare. Assicurati che questo file esista e contenga `connection_type: stdio` (o lo ometta).
*   **`env`**: Puoi definire qui variabili d'ambiente se il tuo server Python è stato modificato per leggerle (es. `os.environ.get('MIA_VARIABILE')`).

Dopo aver salvato questa configurazione, riavvia il client MCP (o ricarica la finestra VS Code). Il client dovrebbe ora essere in grado di avviare il tuo server Odoo MCP e comunicare con esso tramite stdio.

**Nota sulla Modalità `sse`:**

La modalità `connection_type: sse` **non è compatibile** con i client MCP standard basati su stdio. Richiede un client HTTP personalizzato che possa inviare richieste POST all'endpoint `/mcp` e ascoltare eventi sull'endpoint `/events`.

## 🐳 Esecuzione con Docker

È possibile costruire ed eseguire il server MCP Odoo all'interno di un container Docker utilizzando il `Dockerfile` fornito.

**1. Costruire l'Immagine Docker:**

Assicurati di avere Docker installato e in esecuzione. Esegui il seguente comando dalla directory principale del progetto (dove si trova il `Dockerfile`):

```bash
docker build -t odoo-mcp-server:latest .
```

Questo comando costruirà l'immagine Docker con il tag `odoo-mcp-server:latest`.

**2. Eseguire il Container Docker:**

Per eseguire il server, avvia un container dall'immagine appena costruita. È **fondamentale** passare la configurazione necessaria (come URL di Odoo, database, credenziali) tramite variabili d'ambiente (`-e` flag). Il server all'interno del container leggerà queste variabili per configurarsi.

```bash
# Esempio per modalità stdio
docker run --rm -it \
  -e ODOO_URL="http://tuo_odoo_host:8069" \
  -e ODOO_DB="nome_tuo_db" \
  -e ODOO_USER="utente_odoo" \
  -e ODOO_PASSWORD="password_odoo" \
  # Aggiungi altre variabili d'ambiente necessarie basate sulla tua configurazione
  # -e PROTOCOL="xmlrpc"  # Esempio
  # -e CONNECTION_TYPE="stdio" # Esempio (implicito se non specificato nel codice)
  # -e LOGGING_LEVEL="INFO" # Esempio
  odoo-mcp-server:latest
```

*   Sostituisci i valori di esempio (`http://tuo_odoo_host:8069`, `nome_tuo_db`, ecc.) con quelli reali della tua istanza Odoo.
*   Il flag `--rm` rimuove il container una volta fermato.
*   Il flag `-it` permette l'interattività (utile per la modalità `stdio`).
*   **Importante:** Il codice del server (`odoo_mcp.core.mcp_server` o dove viene gestita la configurazione) deve essere in grado di leggere queste variabili d'ambiente (es. tramite `os.environ.get('ODOO_URL')`) e usarle per sovrascrivere o popolare i valori di configurazione. Se il server legge ancora *esclusivamente* dai file YAML, questo approccio non funzionerà senza modifiche al codice Python o montando un file di configurazione come volume (`-v ./percorso/config.prod.yaml:/app/odoo_mcp/config/config.prod.yaml`). Il `Dockerfile` attuale non copia i file di configurazione nell'immagine, privilegiando l'approccio con variabili d'ambiente.

## 🐳🔗 Esempio Avanzato: Docker Compose con n8n come Client MCP

Questo esempio mostra come eseguire sia il server Odoo MCP che un'istanza di n8n (che funge da client MCP) utilizzando Docker Compose. Il server MCP si connetterà a un'istanza Odoo esterna.

**1. Crea il file `docker-compose.yml`:**

Crea un file chiamato `docker-compose.yml` nella directory principale del progetto con il seguente contenuto (o usa quello creato automaticamente se hai seguito i passaggi precedenti):

```yaml
version: '3.8'

services:
  odoo-mcp-server:
    build: 
      context: . # Costruisce l'immagine dalla directory corrente
      dockerfile: Dockerfile
    container_name: odoo_mcp_server_compose
    restart: unless-stopped
    environment:
      # --- Configurazione Odoo (passata al server MCP) ---
      # !!! SOSTITUISCI CON I TUOI VALORI REALI !!!
      - ODOO_URL=https://tuo.odoo.esterno.com 
      - ODOO_DB=nome_tuo_db_esterno
      - ODOO_USER=utente_odoo_per_mcp
      - ODOO_PASSWORD=password_o_apikey_odoo_per_mcp
      # --- Configurazione Server MCP (opzionale, sovrascrive default nel codice) ---
      # Assicurati che il tuo mcp_server.py legga queste variabili d'ambiente
      # o modifica il Dockerfile/codice per usare un file di config montato.
      - PROTOCOL=xmlrpc # o jsonrpc
      - CONNECTION_TYPE=stdio # NECESSARIO per comunicazione MCP tra container
      - LOGGING_LEVEL=INFO 
      # Aggiungi altre variabili d'ambiente se il tuo mcp_server.py le legge
    # Non esporre porte se usa solo stdio per MCP

  n8n:
    image: n8nio/n8n:latest # Usa l'immagine ufficiale di n8n
    container_name: n8n_mcp_client
    restart: unless-stopped
    ports:
      - "5678:5678" # Esponi la porta standard di n8n sull'host
    environment:
      # --- Configurazione n8n standard ---
      - N8N_HOST=localhost # O il tuo dominio/IP se accessibile esternamente
      - N8N_PORT=5678
      - N8N_PROTOCOL=http
      - NODE_ENV=production
      - WEBHOOK_URL=http://localhost:5678/ # URL per i webhook (adatta se necessario)
      # --- Configurazione Client MCP per n8n ---
      # Definisce il server MCP Odoo per n8n. Il client (n8n) avvierà il comando
      # specificato *all'interno del contesto del container odoo-mcp-server*.
      # Docker Compose gestisce la rete tra i container.
      # La sintassi JSON deve essere su una sola riga o correttamente escapata.
      # Usiamo le variabili definite nel servizio 'odoo-mcp-server'.
      - MCP_SERVERS={"odoo-docker":{"command":"python","args":["-m","odoo_mcp.core.mcp_server"],"env":{"ODOO_URL":"${ODOO_URL}","ODOO_DB":"${ODOO_DB}","ODOO_USER":"${ODOO_USER}","ODOO_PASSWORD":"${ODOO_PASSWORD}","PROTOCOL":"${PROTOCOL:-xmlrpc}","CONNECTION_TYPE":"stdio","LOGGING_LEVEL":"${LOGGING_LEVEL:-INFO}"},"enable":true,"autoApprove":[]}}
    volumes:
      - n8n_data:/home/node/.n8n # Volume per persistere i dati di n8n
    depends_on:
      - odoo-mcp-server # Assicura che il server MCP parta prima (o almeno insieme)

volumes:
  n8n_data: # Definisce il volume per n8n

```

**Note Importanti:**

*   **Credenziali Odoo:** **Devi** sostituire i placeholder (`https://tuo.odoo.esterno.com`, `nome_tuo_db_esterno`, ecc.) nel servizio `odoo-mcp-server` con le credenziali reali della tua istanza Odoo esterna.
*   **Lettura Variabili d'Ambiente:** Questo esempio presuppone che il tuo `odoo_mcp/core/mcp_server.py` sia stato modificato per leggere la configurazione (URL Odoo, DB, utente, password, protocollo, ecc.) dalle variabili d'ambiente. Se legge ancora solo dal file YAML, dovrai:
    *   Modificare il codice Python per dare priorità alle variabili d'ambiente.
    *   Oppure, modificare il `Dockerfile` per copiare un file di configurazione e il `docker-compose.yml` per montare un file di configurazione specifico come volume nel container `odoo-mcp-server`. L'approccio con variabili d'ambiente è generalmente preferito per Docker.
*   **`MCP_SERVERS` per n8n:** La variabile `MCP_SERVERS` definisce come n8n (il client) deve avviare il server MCP.
    *   `"command":"python"` e `"args":["-m","odoo_mcp.core.mcp_server"]`: Indicano il comando da eseguire *all'interno* del container `odoo-mcp-server` (corrispondente al `CMD` nel `Dockerfile`).
    *   `"env":{...}`: Passa le variabili d'ambiente necessarie al processo del server MCP avviato da n8n. Utilizza la sintassi `${VAR}` di Docker Compose per prendere i valori definiti nel servizio `odoo-mcp-server`.
    *   `"enable":true`: Abilita questo server per n8n.

**2. Eseguire con Docker Compose:**

Assicurati di avere Docker e Docker Compose installati. Esegui il seguente comando dalla directory principale del progetto (dove si trovano `Dockerfile` e `docker-compose.yml`):

```bash
docker-compose up -d
```

Questo comando:
*   Costruirà l'immagine `odoo-mcp-server` (se non già presente).
*   Scaricherà l'immagine `n8n`.
*   Avvierà entrambi i container in background (`-d`).
*   Configurerà la rete interna affinché n8n possa comunicare con `odoo-mcp-server`.

Ora dovresti poter accedere a n8n all'indirizzo `http://localhost:5678` e utilizzare i nodi MCP (se disponibili in n8n) che faranno riferimento al server `odoo-docker` per interagire con la tua istanza Odoo esterna tramite il server MCP containerizzato.

**3. Fermare i Container:**

Per fermare i container esegui:

```bash
docker-compose down
```

## 🏗️ Architettura

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

## 🗺️ TODO / Roadmap Futura

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

## 📜 Licenza

(Licenza MIT confermata nel file `LICENSE`)

Questo progetto è rilasciato sotto la licenza MIT. Vedere il file `LICENSE` per i dettagli.
