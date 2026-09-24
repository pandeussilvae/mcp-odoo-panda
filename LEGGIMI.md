# mcp-odoo-panda

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/protocol-MCP-green.svg)](https://modelcontextprotocol.io/)

**Un server MCP per Odoo** — permette a Claude, Cursor o qualsiasi client MCP di cercare, leggere, creare, aggiornare e chiamare metodi sul tuo ERP Odoo.

Per sviluppatori e integrator che vogliono gli strumenti Odoo nel client LLM senza scrivere un connettore ad hoc.

<div align="center">
  <img src="assets/Odoo%20MCP%20Server.png" alt="Odoo MCP Server" width="100%"/>
</div>

> Guida completa in inglese: [README.md](README.md)

## Avvio rapido

**Requisiti:** Python 3.10+, un'istanza Odoo 15+ raggiungibile.

1. **Installa**
   ```bash
   git clone https://github.com/pandeussilvae/mcp-odoo-panda.git
   cd mcp-odoo-panda
   pip install .
   ```

2. **Configura dall'esempio**
   ```bash
   cp odoo_mcp/config/config.example.yaml odoo_mcp/config/config.yaml
   # modifica config.yaml — odoo_url, database, username, api_key
   ```

3. **Scegli come si collega il client**
   | Modalità | Quando usarla |
   |----------|----------------|
   | `stdio` (default) | Claude Desktop / Cursor sulla stessa macchina |
   | `streamable_http` | Client remoti o HTTP (`POST /mcp`) |

4. **Avvia**
   ```bash
   odoo-mcp-server --config odoo_mcp/config/config.yaml
   ```

5. **Collega Claude o Cursor** — vedi sotto.

Alternativa Docker: `docker compose up -d` (stack di laboratorio; [default solo-dev](#sicurezza)).

## Config minima

```yaml
odoo_url: http://localhost:8069
database: your_database
username: your_username
api_key: your_password_or_api_key

protocol: xmlrpc
connection_type: stdio
transport_type: stdio
```

Le variabili d'ambiente hanno priorità sul file: `ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_PASSWORD`.

## stdio vs streamable_http

- **stdio** — il client MCP avvia il processo e comunica su stdin/stdout. Ideale per app desktop. Nessuna porta aperta.
- **streamable_http** — il server ascolta in HTTP (`POST /mcp`). Per client remoti o endpoint di rete.

`0.0.0.0` e CORS `*` sono **solo per sviluppo**. In produzione: loopback / interfaccia privata e origini esplicite.

## Collega Claude o Cursor

Esempio Cursor (Impostazioni → MCP):

```json
{
  "mcpServers": {
    "odoo": {
      "command": "odoo-mcp-server",
      "args": ["--config", "/percorso/assoluto/mcp-odoo-panda/odoo_mcp/config/config.yaml"]
    }
  }
}
```

Claude Desktop usa la stessa forma in `claude_desktop_config.json`. Percorsi assoluti; non committare password reali.

## Sicurezza

- **Non committare password o API key reali.** `config.yaml` è locale (gitignored); resta tracciato solo `config.example.yaml`.
- Default `admin` in Compose/Dockerfile: **solo laboratorio**.
- Bind `0.0.0.0` e `allowed_origins: ["*"]`: **solo sviluppo**.

## Standalone

Progetto MIT indipendente per una singola connessione Odoo — non è un gateway SaaS multi-tenant. Dettagli: [ODWARD_BOUNDARY.md](ODWARD_BOUNDARY.md).

Opzionale: usato da [Odward Connect](https://www.techlab.it) come motore MCP a monte; l'integrazione resta fuori da questo repository.

## Documentazione approfondita

Vedi la tabella in [README.md](README.md#deeper-docs) (`CONFIGURATION.md`, `docs/`, …). Note storiche `README_*_fix.md` e `test_*.py` in root sono per i maintainer, non per il primo avvio.

## Licenza

MIT — [LICENSE](LICENSE).

---

Sviluppato da [Paolo Nugnes](https://github.com/pandeussilvae) e [TechLab](https://www.techlab.it) · [info@techlab.it](mailto:info@techlab.it) · [support@techlab.it](mailto:support@techlab.it)
