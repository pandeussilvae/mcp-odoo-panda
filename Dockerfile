# Usa un'immagine Python 3.12 ufficiale (basata su Debian Bookworm) come immagine base
FROM python:3.12-slim-bookworm

# Imposta la directory di lavoro nel container
WORKDIR /app

# Copia il file delle dipendenze
# Assumendo che pyproject.toml definisca le dipendenze e il pacchetto
COPY pyproject.toml ./

# Installa le dipendenze di sistema necessarie (se ce ne sono)
# Esempio: RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Installa le dipendenze Python
# Aggiorna pip e installa le dipendenze dal pyproject.toml
RUN pip install --upgrade pip
RUN pip install .

# Copia il codice sorgente dell'applicazione nella directory di lavoro
COPY ./odoo_mcp ./odoo_mcp

# Comando per eseguire l'applicazione quando il container si avvia
# Assumendo che il server si avvii eseguendo il modulo mcp_server
# Modifica questo comando se il punto di ingresso è diverso
CMD ["python", "-m", "odoo_mcp.core.mcp_server"]

# Nota: Le configurazioni (come URL Odoo, credenziali) dovrebbero essere
# passate tramite variabili d'ambiente (es. -e ODOO_URL=...)
# o montate come volumi al momento dell'esecuzione del container.
# Il codice Python dovrà leggere queste variabili d'ambiente (es. os.environ.get('ODOO_URL')).
