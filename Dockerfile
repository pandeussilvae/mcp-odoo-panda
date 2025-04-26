# Usa un'immagine Python 3.9 ufficiale (basata su Debian Bookworm) come immagine base
FROM python:3.9-slim-bookworm

# Imposta la directory di lavoro nel container
WORKDIR /app

# Installa le dipendenze di sistema necessarie
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia i file di configurazione
COPY pyproject.toml ./
COPY README.md ./
COPY LICENSE ./

# Installa le dipendenze Python
RUN pip install --upgrade pip && \
    pip install .[caching] && \
    pip install pytest pytest-asyncio flake8 mypy

# Copia il codice sorgente dell'applicazione
COPY ./odoo_mcp ./odoo_mcp

# Crea una directory per i log
RUN mkdir -p /app/logs && \
    chmod 777 /app/logs

# Imposta le variabili d'ambiente predefinite
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PROTOCOL=xmlrpc \
    CONNECTION_TYPE=stdio \
    LOGGING_LEVEL=INFO

# Comando per eseguire l'applicazione
CMD ["python", "-m", "odoo_mcp.core.mcp_server"]

# Nota: Le configurazioni Odoo (URL, credenziali) devono essere
# passate tramite variabili d'ambiente al momento dell'esecuzione:
# - ODOO_URL
# - ODOO_DB
# - ODOO_USER
# - ODOO_PASSWORD
