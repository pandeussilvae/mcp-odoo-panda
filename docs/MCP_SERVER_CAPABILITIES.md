# MCP Odoo Server - Capabilities Complete

## 🚀 **Panoramica Completa delle Capabilities**

Il server MCP Odoo espone un set completo di **tool**, **prompt** e **risorse** per l'integrazione con Odoo 18 Community Edition.

---

## 🔧 **TOOL ORM COMPLETI**

### **Schema Introspection Tools**

#### 1. `odoo.schema.version`
- **Descrizione**: Ottiene la versione corrente dello schema Odoo
- **Autenticazione**: Globale (automatica)
- **Parametri**: Nessuno
- **Risposta**: `{"version": "a1b2c3d4e5f6g7h8"}`

#### 2. `odoo.schema.models`
- **Descrizione**: Lista i modelli accessibili in Odoo
- **Autenticazione**: Globale (automatica)
- **Parametri**: 
  - `with_access` (boolean, optional): Filtra per diritti di accesso (default: true)
- **Risposta**: `{"models": ["res.partner", "sale.order", "account.move"]}`

#### 3. `odoo.schema.fields`
- **Descrizione**: Ottiene i campi per un modello specifico
- **Autenticazione**: Globale (automatica)
- **Parametri**:
  - `model` (string): Nome del modello
- **Risposta**: Array di definizioni campo con metadati completi

### **Domain Validation Tools**

#### 4. `odoo.domain.validate`
- **Descrizione**: Valida e compila un'espressione di dominio
- **Autenticazione**: Globale (automatica)
- **Parametri**:
  - `model` (string): Nome del modello
  - `domain_json` (object): Espressione di dominio in formato JSON
- **Risposta**: Validazione e metadati del dominio

#### 5. `odoo.domain.compile`
- **Descrizione**: Compila un'espressione di dominio in formato Odoo
- **Autenticazione**: Globale (automatica)
- **Parametri**:
  - `model` (string): Nome del modello
  - `domain_json` (object): Espressione di dominio
- **Risposta**: Dominio compilato pronto per Odoo

### **CRUD Operations Tools**

#### 6. `odoo.records.search_read`
- **Descrizione**: Cerca e legge record con filtri avanzati
- **Autenticazione**: Globale (automatica)
- **Parametri**:
  - `model` (string): Nome del modello
  - `domain` (array): Filtri di ricerca
  - `fields` (array, optional): Campi da restituire
  - `limit` (integer, optional): Limite record (default: 100)
  - `offset` (integer, optional): Offset per paginazione
- **Risposta**: Array di record con dati

#### 7. `odoo.records.create`
- **Descrizione**: Crea nuovi record in Odoo
- **Autenticazione**: Globale (automatica)
- **Parametri**:
  - `model` (string): Nome del modello
  - `values` (object): Valori del record
  - `operation_id` (string, optional): ID operazione per idempotenza
- **Risposta**: ID del record creato

#### 8. `odoo.records.write`
- **Descrizione**: Modifica record esistenti
- **Autenticazione**: Globale (automatica)
- **Parametri**:
  - `model` (string): Nome del modello
  - `record_ids` (array): ID dei record da modificare
  - `values` (object): Nuovi valori
  - `operation_id` (string, optional): ID operazione per idempotenza
- **Risposta**: Conferma operazione

#### 9. `odoo.records.unlink`
- **Descrizione**: Elimina record
- **Autenticazione**: Globale (automatica)
- **Parametri**:
  - `model` (string): Nome del modello
  - `record_ids` (array): ID dei record da eliminare
  - `operation_id` (string, optional): ID operazione per idempotenza
- **Risposta**: Conferma eliminazione

### **Action Discovery Tools**

#### 10. `odoo.actions.next_steps`
- **Descrizione**: Ottiene suggerimenti per i prossimi passi su un record
- **Autenticazione**: Globale (automatica)
- **Parametri**:
  - `model` (string): Nome del modello
  - `record_id` (integer): ID del record
- **Risposta**: Suggerimenti di azioni disponibili

#### 11. `odoo.actions.call`
- **Descrizione**: Chiama un metodo di azione su un record
- **Autenticazione**: Globale (automatica)
- **Parametri**:
  - `model` (string): Nome del modello
  - `record_id` (integer): ID del record
  - `method` (string): Nome del metodo da chiamare
  - `parameters` (object, optional): Parametri del metodo
  - `operation_id` (string, optional): ID operazione per idempotenza
- **Risposta**: Risultato dell'azione

### **Utility Tools**

#### 12. `odoo.picklists`
- **Descrizione**: Ottiene valori picklist per un campo
- **Autenticazione**: Globale (automatica)
- **Parametri**:
  - `model` (string): Nome del modello
  - `field` (string): Nome del campo
  - `limit` (integer, optional): Numero massimo di valori (default: 100)
- **Risposta**: Array di valori disponibili

#### 13. `odoo.name_search`
- **Descrizione**: Ricerca per nome in campi relazionali
- **Autenticazione**: Globale (automatica)
- **Parametri**:
  - `model` (string): Nome del modello
  - `name` (string): Termine di ricerca
  - `limit` (integer, optional): Limite risultati (default: 100)
- **Risposta**: Array di risultati con ID e nome

---

## 📝 **PROMPT DISPONIBILI**

### **Record Management Prompts**

#### 1. `analyze-record`
- **Descrizione**: Analizza un record Odoo esistente
- **Template**: `"Analyze the record {model}/{id}"`
- **Parametri**:
  - `model` (string): Nome del modello
  - `id` (integer): ID del record
- **Utilizzo**: Per ottenere analisi dettagliate di record specifici

#### 2. `create-record`
- **Descrizione**: Crea un nuovo record Odoo
- **Template**: `"Create a new record in {model}"`
- **Parametri**:
  - `model` (string): Nome del modello
  - `values` (object): Valori del record
- **Utilizzo**: Per guidare la creazione di nuovi record

#### 3. `update-record`
- **Descrizione**: Aggiorna un record Odoo esistente
- **Template**: `"Update record {model}/{id}"`
- **Parametri**:
  - `model` (string): Nome del modello
  - `id` (integer): ID del record
  - `values` (object): Nuovi valori
- **Utilizzo**: Per guidare l'aggiornamento di record esistenti

---

## 📊 **RISORSE ESPOSTE**

### **Resource Templates**

#### 1. `res.partner`
- **Tipo**: Model Resource
- **Descrizione**: Risorsa Partner/Contatto Odoo
- **Operazioni**: `["create", "read", "update", "delete", "search"]`
- **URI Template**: `odoo://res.partner/{id}`
- **List URI**: `odoo://res.partner/list`
- **Binary URI**: `odoo://res.partner/binary/{field}/{id}`

#### 2. `res.users`
- **Tipo**: Model Resource
- **Descrizione**: Risorsa Utente Odoo
- **Operazioni**: `["create", "read", "update", "delete", "search"]`
- **URI Template**: `odoo://res.users/{id}`
- **List URI**: `odoo://res.users/list`
- **Binary URI**: `odoo://res.users/binary/{field}/{id}`

#### 3. `sale.order`
- **Tipo**: Model Resource
- **Descrizione**: Risorsa Ordine di Vendita Odoo
- **Operazioni**: `["create", "read", "update", "delete", "search"]`
- **URI Template**: `odoo://sale.order/{id}`
- **List URI**: `odoo://sale.order/list`
- **Binary URI**: `odoo://sale.order/binary/{field}/{id}`

#### 4. `account.move`
- **Tipo**: Model Resource
- **Descrizione**: Risorsa Movimento Contabile Odoo
- **Operazioni**: `["create", "read", "update", "delete", "search"]`
- **URI Template**: `odoo://account.move/{id}`
- **List URI**: `odoo://account.move/list`
- **Binary URI**: `odoo://account.move/binary/{field}/{id}`

#### 5. `product.product`
- **Tipo**: Model Resource
- **Descrizione**: Risorsa Prodotto Odoo
- **Operazioni**: `["create", "read", "update", "delete", "search"]`
- **URI Template**: `odoo://product.product/{id}`
- **List URI**: `odoo://product.product/list`
- **Binary URI**: `odoo://product.product/binary/{field}/{id}`

### **Resource Types**

#### **Model Resources**
- **URI Format**: `odoo://{model}/{id}`
- **Content**: Record data in JSON format
- **MIME Type**: `application/json`
- **Operations**: CRUD + Search

#### **List Resources**
- **URI Format**: `odoo://{model}/list`
- **Content**: Array of records with pagination
- **MIME Type**: `application/json`
- **Operations**: Read + Search

#### **Binary Resources**
- **URI Format**: `odoo://{model}/binary/{field}/{id}`
- **Content**: Binary data (base64 encoded)
- **MIME Type**: `application/octet-stream`
- **Operations**: Read + Update

---

## 🔐 **SICUREZZA E AUTENTICAZIONE**

### **Global Authentication**
- ✅ **Autenticazione automatica** per tutti i tool
- ✅ **Nessun parametro user_id** richiesto
- ✅ **Compatibilità immediata** con architettura esistente
- ✅ **Zero downtime** deployment
- ✅ **Enterprise grade** security

### **Security Features**
- ✅ **PII Masking**: Mascheramento dati sensibili
- ✅ **Rate Limiting**: Controllo velocità richieste
- ✅ **Audit Logging**: Log completo delle operazioni
- ✅ **Implicit Domains**: Domini di sicurezza automatici
- ✅ **Input Validation**: Validazione completa input

### **Access Control**
- ✅ **Permission-based**: Rispetta permessi Odoo
- ✅ **Model-level**: Controllo accesso per modello
- ✅ **Field-level**: Controllo accesso per campo
- ✅ **Record-level**: Controllo accesso per record

---

## 📡 **PROTOCOLLI DI COMUNICAZIONE**

### **1. stdio**
- **Descrizione**: Comunicazione diretta via stdin/stdout
- **Utilizzo**: CLI e script automation
- **Formato**: JSON-RPC

### **2. streamable_http**
- **Descrizione**: HTTP con supporto streaming
- **Utilizzo**: Web applications e API integration
- **Porta**: 8080 (configurabile)

### **3. sse**
- **Descrizione**: Server-Sent Events per aggiornamenti real-time
- **Utilizzo**: Real-time notifications e updates
- **WebSocket**: Supporto completo

---

## 🚀 **ESEMPI DI UTILIZZO**

### **Tool Usage Example**
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "odoo.records.search_read",
    "arguments": {
      "model": "res.partner",
      "domain": [["is_company", "=", true]],
      "fields": ["name", "email", "phone"],
      "limit": 10
    }
  },
  "id": 1
}
```

### **Prompt Usage Example**
```json
{
  "jsonrpc": "2.0",
  "method": "prompts/get",
  "params": {
    "name": "analyze-record",
    "arguments": {
      "model": "res.partner",
      "id": 123
    }
  },
  "id": 1
}
```

### **Resource Usage Example**
```json
{
  "jsonrpc": "2.0",
  "method": "resources/read",
  "params": {
    "uri": "odoo://res.partner/123"
  },
  "id": 1
}
```

---

## 📈 **PERFORMANCE E LIMITI**

### **Rate Limiting**
- **Default**: 60 richieste/minuto
- **Burst**: 100 richieste
- **Configurabile**: Via environment variables

### **Payload Limits**
- **Max Size**: 1MB (configurabile)
- **Max Fields**: 100 (configurabile)
- **Max Records**: 200 (configurabile)

### **Caching**
- **Schema Cache**: 600 secondi TTL
- **Connection Pool**: 5-10 connessioni (configurabile)
- **Session Timeout**: 60 minuti (configurabile)

---

## 🔧 **CONFIGURAZIONE**

### **Environment Variables**
```bash
# Odoo Connection
ODOO_URL=http://odoo:8069
ODOO_DB=odoo
ODOO_USER=admin
ODOO_PASSWORD=your_password

# MCP Server
PROTOCOL=xmlrpc
CONNECTION_TYPE=streamable_http
LOGGING_LEVEL=INFO

# Performance
POOL_SIZE=5
TIMEOUT=30
REQUESTS_PER_MINUTE=60
```

### **Security Settings**
```bash
# Security
PII_MASKING=true
AUDIT_LOGGING=true
IMPLICIT_DOMAINS=true
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_BURST=100
```

---

## 📚 **DOCUMENTAZIONE AGGIUNTIVA**

- 📖 **`README_REFACTORED.md`** - Panoramica generale
- 🔧 **`docs/API_REFERENCE.md`** - Riferimento API completo
- 👨‍💻 **`docs/DEVELOPER_GUIDE.md`** - Guida sviluppatori
- 🐳 **`docs/DOCKER_DEPLOYMENT.md`** - Guida deployment Docker
- 🔒 **`docs/GIT_AND_CACHE_MANAGEMENT.md`** - Gestione cache e Git

---

## ✅ **STATO: PRODUCTION READY**

**Il server MCP Odoo espone un set completo e professionale di capabilities per l'integrazione con Odoo 18, con autenticazione globale, sicurezza enterprise e performance ottimizzate.**
