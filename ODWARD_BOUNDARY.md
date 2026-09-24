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
