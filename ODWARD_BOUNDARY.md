# Odward integration boundary

`mcp-odoo-panda` is an **independent** MIT MCP server for Odoo
([upstream](https://github.com/pandeussilvae/mcp-odoo-panda)).

## Do not put in this repo

- Odward `si_id` / `RoutingContext` / tenant models
- `setup_url` / instance onboarding tokens / hosted `/connect/*` pages
- Imports from `workflow_executor` or Odward credentials vault
- MCP Apps (`io.modelcontextprotocol/ui`) or channel bridges (WA/TG)

## Odward owns (adapter)

Multi-tenant routing, Bearer `odoo_mcp_access`,
`io.modelcontextprotocol/oauth-client-credentials` on the public path,
`setup_url` / hosted connect UI errors, and feature flag `ODOO_MCP_GATEWAY` live in:

- `services/workflow_executor/executor/mcp/routing.py`
- `services/workflow_executor/executor/mcp/odward_adapter.py`
- `services/workflow_executor/executor/odoo_instance/`

The Odward stack **instantiates** panda with connection config; it does not
fork Odward domain logic into `odoo_mcp/`.

## Protocol target

Odward deploys panda with `CONNECTION_TYPE=mcp_2026_07_28` via the official
Python SDK (`mcp>=2.1.1,<3`, module `odoo_mcp.core.mcp_sdk_server`):

- Streamable HTTP **POST `/mcp`** (stateless JSON)
- `protocolVersion: "2026-07-28"`
- Methods: `server/discover`, `tools/list`, `tools/call` — **no** `initialize` / session id
- Optional per-request overlay: `X-Odoo-Url` / `X-Odoo-Db` / `X-Odoo-User` / `X-Odoo-Password`
  (see `ephemeral_odoo.py`)

Config remains YAML/env single-connection (`ODOO_URL`, `ODOO_DB`, user/password)
when headers are absent.

## Extensions in panda

- **`io.modelcontextprotocol/tasks`** (opt-in): advertised in
  `capabilities.extensions`; clients that declare the extension (or
  `clientCapabilities.tasks`) may pass `"async": true` on long ORM tools and
  poll with `tasks/get` / `tasks/cancel`. Clients without the extension stay
  fully synchronous.

## Extensions / UX in Odward (not panda)

- **`io.modelcontextprotocol/oauth-client-credentials`** on `/mcp/odoo`
- Hosted connect UI (`/connect/odoo`, future `/connect/{system}`) — credentials
  only there (GUI NO PAIN); channels receive `setup_url` CTAs, never passwords
