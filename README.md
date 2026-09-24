# mcp-odoo-panda

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/protocol-MCP-green.svg)](https://modelcontextprotocol.io/)

**An MCP server for Odoo** — let Claude, Cursor, or any MCP client search, read, create, update, and call methods on your Odoo ERP.

For developers and integrators who want Odoo tools inside an LLM client without writing a custom connector.

<div align="center">
  <img src="assets/Odoo%20MCP%20Server.png" alt="Odoo MCP Server" width="100%"/>
</div>

## Quickstart

**Requirements:** Python 3.10+, an Odoo 15+ instance you can reach (local or remote).

1. **Install**
   ```bash
   git clone https://github.com/pandeussilvae/mcp-odoo-panda.git
   cd mcp-odoo-panda
   pip install .
   ```

2. **Configure from the example**
   ```bash
   cp odoo_mcp/config/config.example.yaml odoo_mcp/config/config.yaml
   # edit config.yaml — set odoo_url, database, username, api_key
   ```

3. **Choose how clients connect**
   | Mode | When to use |
   |------|-------------|
   | `stdio` (default) | Claude Desktop / Cursor on the same machine |
   | `streamable_http` | Remote or HTTP clients (`POST /mcp`) |

   Set `connection_type` / `transport_type` in `config.yaml` (see [stdio vs HTTP](#stdio-vs-streamable_http)).

4. **Run**
   ```bash
   odoo-mcp-server --config odoo_mcp/config/config.yaml
   # or: python -m odoo_mcp.core.mcp_server --config odoo_mcp/config/config.yaml
   ```

5. **Connect your MCP client** (Claude Desktop / Cursor) — see [Connect Claude or Cursor](#connect-claude-or-cursor).

Docker alternative: `docker compose up -d` (lab stack; [dev-only defaults](#security)).

## Minimal config

Copy-paste starting point (`odoo_mcp/config/config.yaml`):

```yaml
odoo_url: http://localhost:8069
database: your_database
username: your_username
api_key: your_password_or_api_key

protocol: xmlrpc
connection_type: stdio
transport_type: stdio
```

Environment variables override the file when set: `ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_PASSWORD`.

## stdio vs streamable_http

- **stdio** — the MCP client starts this process and talks over stdin/stdout. Best for desktop apps (Claude, Cursor). No open port.
- **streamable_http** — the server listens on HTTP (`POST /mcp`). Use when the client is remote or you need a network endpoint.

Legacy `sse` exists for older setups; prefer `stdio` or `streamable_http` for new work.

HTTP example (dev):

```yaml
connection_type: streamable_http
transport_type: streamable_http
http:
  host: 127.0.0.1   # prefer loopback; 0.0.0.0 is DEV-ONLY
  port: 8080
  streamable: true
```

## Connect Claude or Cursor

**Cursor** — add an MCP server entry (Settings → MCP), for example:

```json
{
  "mcpServers": {
    "odoo": {
      "command": "odoo-mcp-server",
      "args": ["--config", "/absolute/path/to/mcp-odoo-panda/odoo_mcp/config/config.yaml"]
    }
  }
}
```

**Claude Desktop** — same shape in its MCP config file (`claude_desktop_config.json`): `command` + `args` pointing at your install and config.

Use absolute paths. Do not commit client configs that embed real passwords.

## What you get

- Search / read / create / write / unlink Odoo records
- Call custom model methods
- Session handling, rate limiting, optional HTTP CORS
- Optional modern MCP Streamable HTTP (`CONNECTION_TYPE=mcp_2026_07_28` in Docker/env)

## Security

- **Never commit real passwords or API keys.** Keep `config.yaml` local (it is gitignored); only `config.example.yaml` is tracked.
- Compose / Dockerfile `admin` password defaults are **DEV-ONLY** for a local lab.
- Binding `0.0.0.0` and CORS `allowed_origins: ["*"]` are **DEV-ONLY**. In production use loopback or a private interface and explicit origins.
- Prefer env vars or a secrets manager for credentials.

## Standalone

This project is a standalone MIT MCP server for a single Odoo connection. It is not a multi-tenant SaaS gateway. See [ODWARD_BOUNDARY.md](ODWARD_BOUNDARY.md).

Optional: used by [Odward Connect](https://www.techlab.it) as an upstream engine; that integration lives outside this repo.

## Deeper docs

| Doc | Topic |
|-----|--------|
| [CONFIGURATION.md](CONFIGURATION.md) | Full configuration reference |
| [docs/API_REFERENCE.md](docs/API_REFERENCE.md) | Tools / API |
| [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) | Architecture for contributors |
| [docs/DOCKER_DEPLOYMENT.md](docs/DOCKER_DEPLOYMENT.md) | Docker notes |
| [docs/server_usage.md](docs/server_usage.md) | Server usage |
| [LEGGIMI.md](LEGGIMI.md) | Italian quickstart |

Historical refactor notes (when present) live under [`docs/archive/`](docs/archive/).

## License

MIT — see [LICENSE](LICENSE).

---

Developed by [Paolo Nugnes](https://github.com/pandeussilvae) and [TechLab](https://www.techlab.it) · [info@techlab.it](mailto:info@techlab.it) · [support@techlab.it](mailto:support@techlab.it)
