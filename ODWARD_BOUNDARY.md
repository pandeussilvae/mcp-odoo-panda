# Standalone boundary

`mcp-odoo-panda` is an **independent** MIT [Model Context Protocol](https://modelcontextprotocol.io/) server for Odoo. It speaks MCP and talks to a single Odoo instance via XML-RPC / JSON-RPC.

## What this repo is

- A reusable MCP server you can run locally (stdio) or over HTTP
- Configured with YAML/JSON or environment variables (`ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_PASSWORD`)
- Agnostic of any particular SaaS product, tenant model, or hosted onboarding UI

## What this repo is not

- Not a multi-tenant SaaS gateway
- Not an OAuth / JWT broker for hosted “connect your Odoo” flows
- Not a channel bridge (WhatsApp, Telegram, etc.)
- Not coupled to any private monorepo adapters or credential vaults

Integrators that need multi-tenant routing, hosted connect UX, or product-specific auth should keep that logic in their own adapter layer and **instantiate** panda with connection config — do not fork SaaS domain types into `odoo_mcp/`.

## Optional note

Used by [Odward Connect](https://www.techlab.it) as an upstream MCP engine; Odward integration stays outside this repository.

## Anti-SSRF ephemeral destination pin (PR-S1)

Indispensable hardening for per-request `X-Odoo-*` overlays:

- `odoo_mcp/core/safe_destination.py` — fail-closed destination policy + IP-pinned TCP/TLS
- `ephemeral_odoo.py` uses that transport; optional `connect_ip` / `X-Odoo-Connect-Ip`
- No Odward domain imports; env flags `ODWARD_ALLOW_*` default off
- Odward Connect sidecar CMD is `run_ephemeral.py` (headers-only). Legacy
  `XMLRPCHandler` / pool paths are **not** on that entrypoint.

### Trust boundary: `X-Odoo-Connect-Ip` + internal token

Panda treats `X-Odoo-Connect-Ip` as a **trusted pin from the integrator**.
The headers-only entrypoint (`run_ephemeral.py`) also requires a dedicated
service-to-service secret:

| Item | Value |
|------|--------|
| Env | `ODWARD_INTERNAL_TOKEN` (min 32 chars; no production default) |
| Header | `X-Odward-Internal-Token` |
| Compare | `secrets.compare_digest` (constant-time) |
| Surface | Entire HTTP app (`/health`, `/mcp`, …) — fail-closed if missing |
| Flag | `ODWARD_REQUIRE_INTERNAL_AUTH=1` (set by `run_ephemeral.py`) |

Requests without a valid token are rejected **before** dispatch / Odoo connect.
The secret must never appear in logs or HTTP responses. Integrators must strip
any client-supplied copy of the header and inject their own.

Destination policy (IP class, TLS SNI/hostname verify, no second DNS) remains
active for authenticated requests.

#### Configure & rotate (Odward Connect)

1. Generate: `openssl rand -hex 32` (or equivalent CSPRNG).
2. Set the same value in gateway + panda env (Compose `env_file` / secrets store).
3. Recreate **both** containers so healthchecks and forwards use the new token.
4. Do not commit the value; do not reuse MCP bearer / JWT / Odoo passwords.
5. Production Compose must **not** publish panda host ports (mesh DNS only).
   Lab may publish loopback via an overlay (e.g. `compose.techlab.yml`).

#### Pre-existing test failures (not gated by Security CI)

Host runs of the full panda suite may still fail in `tests/test_mcp_sdk_server.py`
and parts of `tests/test_domain_dsl.py` due to SDK / environment drift unrelated
to anti-SSRF or internal auth. Security CI gates only the dedicated security
files and must not use `continue-on-error`.

When an integrator ships a pin update, record the submodule SHA in the parent repo.
