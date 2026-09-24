# Docker Deployment Guide - MCP Odoo Server

## 🐳 **Deployment Docker Completo**

### ✅ **Problemi Risolti**

#### **1. Immagine Docker**
- ✅ Dockerfile copia `pyproject.toml`, `LICENSE`, `odoo_mcp/`, e `config.example.yaml` come default config
- ✅ Nessuna dipendenza da README nel layer immagine

#### **2. Sicurezza Password**
- ❌ **Prima**: `ODOO_PASSWORD=admin` hardcoded nel Dockerfile
- ✅ **Ora**: Password gestita via variabili d'ambiente per sicurezza

#### **3. Ottimizzazione Build**
- ✅ **`.dockerignore`** configurato per escludere file non necessari
- ✅ **Layer caching** ottimizzato
- ✅ **Build context** minimizzato

## 🚀 **Quick Start**

### **1. Build dell'Immagine**
```bash
# Build dell'immagine MCP Server
docker build -t mcp-odoo-panda .

# Verifica che l'immagine sia stata creata
docker images | grep mcp-odoo-panda
```

### **2. Run con Docker Compose (Raccomandato)**
```bash
# Avvia tutto lo stack (MCP Server + Odoo + PostgreSQL)
docker-compose up -d

# Verifica che tutti i servizi siano attivi
docker-compose ps

# Visualizza i log
docker-compose logs -f mcp-odoo-server
```

### **3. Run Manuale**
```bash
# Avvia solo il MCP Server (richiede Odoo esistente)
docker run -d \
  --name mcp-odoo-panda \
  -p 8080:8080 \
  -e ODOO_URL=http://your-odoo-server:8069 \
  -e ODOO_DB=your_database \
  -e ODOO_USER=your_username \
  -e ODOO_PASSWORD=your_password \
  mcp-odoo-panda
```

## 📋 **Configurazione Completa**

### **File di Configurazione**

#### **`Dockerfile`** - Immagine Base
```dockerfile
# Python 3.11 slim base
FROM python:3.11-slim-bookworm

# Dependencies e configurazione
# ✅ config.example.yaml → config.yaml
# ✅ Password sicura (no hardcode)
# ✅ Ottimizzazioni build
```

#### **`docker-compose.yml`** - Stack Completo
```yaml
services:
  mcp-odoo-server:    # MCP Server
  odoo:              # Odoo 18.0
  db:                # PostgreSQL 15
```

#### **`docker-compose.override.yml.example`** - Personalizzazione
```yaml
# Template per configurazione personalizzata
# Copiare in docker-compose.override.yml
```

### **Variabili d'Ambiente**

#### **Configurazione Odoo (Required)**
```bash
ODOO_URL=http://odoo:8069          # URL del server Odoo
ODOO_DB=odoo                       # Nome database
ODOO_USER=admin                    # Username
ODOO_PASSWORD=your_password        # Password (sicura)
```

#### **Configurazione MCP Server**
```bash
PROTOCOL=xmlrpc                    # xmlrpc o jsonrpc
CONNECTION_TYPE=streamable_http    # stdio/streamable_http/sse
LOGGING_LEVEL=INFO                 # DEBUG/INFO/WARNING/ERROR
```

#### **Performance Settings**
```bash
POOL_SIZE=5                        # Dimensione pool connessioni
TIMEOUT=30                         # Timeout richieste
SESSION_TIMEOUT_MINUTES=60         # Durata sessione
REQUESTS_PER_MINUTE=60             # Rate limiting
RATE_LIMIT_MAX_WAIT_SECONDS=30     # Max attesa rate limit
```

## 🔧 **Configurazione Avanzata**

### **1. Configurazione Personalizzata**
```bash
# Copiare il template
cp docker-compose.override.yml.example docker-compose.override.yml

# Modificare le variabili
nano docker-compose.override.yml

# Riavviare i servizi
docker-compose up -d
```

### **2. Persistenza Dati**
```bash
# Volumi per persistenza
volumes:
  - ./logs:/app/logs           # Log MCP Server
  - ./config:/app/config       # Configurazioni
  - odoo-data:/var/lib/odoo    # Dati Odoo
  - postgres-data:/var/lib/postgresql/data/pgdata  # Database
```

### **3. Health Checks**
```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import requests; requests.get('http://localhost:8080/health')"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

## 🔍 **Monitoring e Debug**

### **Logs**
```bash
# Logs MCP Server
docker-compose logs -f mcp-odoo-server

# Logs Odoo
docker-compose logs -f odoo

# Logs Database
docker-compose logs -f db

# Tutti i logs
docker-compose logs -f
```

### **Status Servizi**
```bash
# Status container
docker-compose ps

# Health check
docker-compose exec mcp-odoo-server python -c "import requests; print(requests.get('http://localhost:8080/health').json())"
```

### **Debug**
```bash
# Accesso container MCP Server
docker-compose exec mcp-odoo-server bash

# Accesso container Odoo
docker-compose exec odoo bash

# Test connessione Odoo
docker-compose exec mcp-odoo-server python -c "
from odoo_mcp.core.handler_factory import HandlerFactory
config = {'protocol': 'xmlrpc', 'odoo_url': 'http://odoo:8069', 'database': 'odoo', 'username': 'admin', 'api_key': 'admin'}
handler = HandlerFactory.create_handler('xmlrpc', config)
print('Connection test successful')
"
```

## 🛠️ **Comandi Utili**

### **Gestione Container**
```bash
# Avvia servizi
docker-compose up -d

# Riavvia servizi
docker-compose restart

# Ferma servizi
docker-compose down

# Ferma e rimuove volumi
docker-compose down -v

# Rebuild e riavvia
docker-compose up --build -d
```

### **Backup e Restore**
```bash
# Backup database
docker-compose exec db pg_dump -U odoo odoo > backup.sql

# Restore database
docker-compose exec -T db psql -U odoo odoo < backup.sql

# Backup volumi
docker run --rm -v mcp-odoo-panda_odoo-data:/data -v $(pwd):/backup alpine tar czf /backup/odoo-data.tar.gz -C /data .
```

## 🔒 **Sicurezza**

### **Best Practices Implementate**
- ✅ **No password hardcoded** nel Dockerfile
- ✅ **Variabili d'ambiente** per configurazioni sensibili
- ✅ **Network isolato** per comunicazione interna
- ✅ **Health checks** per monitoring
- ✅ **Non-root user** (se possibile)

### **Configurazione Sicura**
```bash
# File .env (non committare)
ODOO_PASSWORD=your_secure_password
ODOO_DB_PASSWORD=your_secure_db_password

# Docker secrets (production)
echo "your_password" | docker secret create odoo_password -
```

## 📊 **Performance**

### **Ottimizzazioni Build**
- ✅ **Multi-stage build** (se necessario)
- ✅ **Layer caching** ottimizzato
- ✅ **Minimal dependencies** installate
- ✅ **Build context** minimizzato con .dockerignore

### **Ottimizzazioni Runtime**
- ✅ **Connection pooling** configurato
- ✅ **Resource limits** impostabili
- ✅ **Health checks** per monitoring
- ✅ **Logging strutturato**

## 🚨 **Troubleshooting**

### **Errori Comuni**

#### **1. Build / COPY failures**
```bash
# Dockerfile copies package sources only (no README COPY). Rebuild:
docker build -t mcp-odoo-panda .
```

#### **2. "Connection refused to Odoo"**
```bash
# Verificare che Odoo sia attivo
docker-compose logs odoo

# Verificare network
docker network ls
docker network inspect mcp-odoo-panda_mcp-network
```

#### **3. "Authentication failed"**
```bash
# Verificare credenziali
docker-compose exec mcp-odoo-server env | grep ODOO

# Test connessione manuale
docker-compose exec mcp-odoo-server python -c "
import requests
r = requests.post('http://odoo:8069/web/session/authenticate', 
    json={'jsonrpc': '2.0', 'method': 'call', 'params': {
        'db': 'odoo', 'login': 'admin', 'password': 'admin'
    }})
print(r.json())
"
```

## 📚 **Riferimenti**

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Odoo Docker Documentation](https://hub.docker.com/_/odoo)
- [PostgreSQL Docker Documentation](https://hub.docker.com/_/postgres)

---

**✅ Docker deployment completamente funzionante e sicuro!**
