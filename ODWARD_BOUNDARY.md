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

### Trust boundary: `X-Odoo-Connect-Ip`

Panda treats `X-Odoo-Connect-Ip` as a **trusted pin from the integrator**.
Anyone who can open TCP to the sidecar HTTP port can supply the header.
Panda still fail-closes disallowed IP classes (private, loopback, link-local,
metadata, …) and keeps TLS SNI/cert verify on the URL hostname.

Authenticity is therefore **not** proven inside panda; it is an integrator
network / auth responsibility (e.g. Odward Connect: gateway builds the overlay
and does not forward client `X-Odoo-*`; sidecar published on loopback / internal
mesh only). Proportionate follow-ups if the mesh is not fully trusted: shared
internal token between gateway and panda, and omit host port publish in prod.

When an integrator ships a pin update, record the submodule SHA in the parent repo.
