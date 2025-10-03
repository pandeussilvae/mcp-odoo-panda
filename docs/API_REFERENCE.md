# 📚 MCP Odoo Server - API Reference

## Overview

This document provides comprehensive API reference for the MCP Odoo Server. All operations use global authentication and maintain backward compatibility with existing implementations.

## 🔐 Authentication

All API operations use **global authentication** with the server's configured credentials:

- **XML-RPC**: Uses `global_uid` and `global_password`
- **JSON-RPC**: Uses `uid` from global authentication
- **No user_id parameter required**: Authentication is automatic

## 📊 Schema Tools

### `odoo.schema.version`

Get the current schema version.

**Parameters:**
- None

**Response:**
```json
{
  "version": "a1b2c3d4e5f6g7h8"
}
```

**Example:**
```bash
curl -X POST http://localhost:8080/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "call_tool",
    "params": {
      "name": "odoo.schema.version",
      "arguments": {}
    },
    "id": 1
  }'
```

### `odoo.schema.models`

List accessible models.

**Parameters:**
- `with_access` (boolean, optional): Filter by access rights (default: true)

**Response:**
```json
{
  "models": [
    "res.partner",
    "sale.order",
    "account.move",
    "res.users"
  ]
}
```

### `odoo.schema.fields`

Get fields for a specific model.

**Parameters:**
- `model` (string): Model name

**Response:**
```json
{
  "fields": [
    {
      "name": "name",
      "ttype": "char",
      "required": true,
      "readonly": false,
      "relation": null,
      "selection": null,
      "domain": null,
      "store": true,
      "compute": null,
      "writeable": true
    }
  ]
}
```

## 🔍 Domain Tools

### `odoo.domain.validate`

Validate and compile a domain expression.

**Parameters:**
- `model` (string): Model name
- `domain_json` (object): Domain expression in JSON format

**Example Domain:**
```json
{
  "and": [
    ["company_id", "in", "__current_company_ids__"],
    ["create_date", ">=", "__start_of_month__"],
    {"or": [["state", "=", "New"], ["probability", ">=", 50]]}
  ]
}
```

**Response:**
```json
{
  "ok": true,
  "compiled": [
    "&", 
    ["company_id", "in", "__current_company_ids__"], 
    ["create_date", ">=", "2024-01-01"], 
    "|", 
    ["state", "=", "New"], 
    ["probability", ">=", 50]
  ],
  "errors": [],
  "hints": ["Valid AND domain"]
}
```

## 📝 CRUD Operations

### `odoo.search_read`

Search and read records with security enhancements.

**Parameters:**
- `model` (string): Model name
- `domain_json` (object, optional): Search domain in JSON format
- `fields` (array, optional): Fields to retrieve
- `limit` (integer, optional): Maximum number of records (default: 50, max: 200)
- `offset` (integer, optional): Number of records to skip (default: 0)
- `order` (string, optional): Order specification

**Response:**
```json
{
  "records": [
    {
      "id": 1,
      "name": "John Doe",
      "email": "john@example.com",
      "phone": "***-***-1234"
    }
  ],
  "count": 25,
  "domain": ["&", ["active", "=", true], ["company_id", "in", [1, 2]]]
}
```

### `odoo.read`

Read specific records.

**Parameters:**
- `model` (string): Model name
- `record_ids` (array): List of record IDs
- `fields` (array, optional): Fields to retrieve

**Response:**
```json
{
  "records": [
    {
      "id": 1,
      "name": "John Doe",
      "email": "john@example.com"
    }
  ]
}
```

### `odoo.create`

Create a new record.

**Parameters:**
- `model` (string): Model name
- `values` (object): Record values
- `operation_id` (string, optional): Operation ID for idempotency

**Response:**
```json
{
  "id": 123,
  "message": "Record created successfully"
}
```

### `odoo.write`

Update existing records.

**Parameters:**
- `model` (string): Model name
- `record_ids` (array): List of record IDs
- `values` (object): Values to write
- `operation_id` (string, optional): Operation ID for idempotency

**Response:**
```json
{
  "updated": 3,
  "message": "Records updated successfully"
}
```

### `odoo.unlink`

Delete records.

**Parameters:**
- `model` (string): Model name
- `record_ids` (array): List of record IDs
- `operation_id` (string, optional): Operation ID for idempotency

**Response:**
```json
{
  "deleted": 2,
  "message": "Records deleted successfully"
}
```

## 🎯 Action Tools

### `odoo.actions.next_steps`

Get next steps suggestions for a record.

**Parameters:**
- `model` (string): Model name
- `record_id` (integer): Record ID

**Response:**
```json
{
  "model": "sale.order",
  "record_id": 123,
  "current_state": "draft",
  "available_actions": [
    {
      "name": "action_confirm",
      "label": "Confirm Order",
      "description": "Confirm the sales order",
      "icon": "check-circle",
      "category": "workflow"
    }
  ],
  "suggested_actions": [
    "action_confirm"
  ],
  "hints": [
    "Current state: draft",
    "Suggested actions: action_confirm, action_cancel"
  ]
}
```

### `odoo.actions.call`

Execute an action method on a record.

**Parameters:**
- `model` (string): Model name
- `record_id` (integer): Record ID
- `method` (string): Method name to call
- `parameters` (object, optional): Method parameters
- `operation_id` (string, optional): Operation ID for idempotency

**Response:**
```json
{
  "result": true,
  "message": "Action executed successfully",
  "data": {
    "new_state": "sale"
  }
}
```

## 🔍 Utility Tools

### `odoo.name_search`

Search records by name.

**Parameters:**
- `model` (string): Model name
- `name` (string): Name to search for
- `operator` (string, optional): Search operator (default: "ilike")
- `limit` (integer, optional): Maximum number of results (default: 10)

**Response:**
```json
{
  "results": [
    [1, "John Doe"],
    [2, "Jane Smith"]
  ]
}
```

### `odoo.picklists`

Get picklist values for a field.

**Parameters:**
- `model` (string): Model name
- `field` (string): Field name
- `limit` (integer, optional): Maximum number of values (default: 100)

**Response:**
```json
{
  "values": [
    {"id": "draft", "label": "Draft"},
    {"id": "sale", "label": "Sales Order"},
    {"id": "done", "label": "Locked"}
  ]
}
```

## 📊 Resource Management

### Resource URIs

Resources are accessed via standardized URIs:

- **Single Record**: `odoo://{model}/{id}`
- **Record List**: `odoo://{model}/list`
- **Binary Field**: `odoo://{model}/binary/{field}/{id}`

### Resource Operations

#### GET Resource

```bash
GET /resources/odoo://res.partner/123
```

**Response:**
```json
{
  "uri": "odoo://res.partner/123",
  "type": "record",
  "content": {
    "id": 123,
    "name": "John Doe",
    "email": "john@example.com"
  },
  "mime_type": "application/json",
  "metadata": {
    "model": "res.partner",
    "last_modified": "2024-01-15T10:30:00Z"
  }
}
```

#### Subscribe to Updates

```bash
GET /resources/odoo://res.partner/list?subscribe=true
```

**Response:**
```
data: {"type": "update", "uri": "odoo://res.partner/123", "content": {...}}

data: {"type": "create", "uri": "odoo://res.partner/124", "content": {...}}
```

## 🚨 Error Handling

### Error Response Format

All errors follow the JSON-RPC 2.0 specification:

```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32000,
    "message": "Error description",
    "data": {
      "exception": "ErrorType",
      "args": ["arg1", "arg2"],
      "original_exception": "Original error message"
    }
  },
  "id": 1
}
```

### Common Error Codes

| Code | Description |
|------|-------------|
| -32000 | General error |
| -32001 | Authentication error |
| -32002 | Network error |
| -32003 | Protocol error |
| -32004 | Configuration error |
| -32005 | Connection error |
| -32006 | Session error |
| -32007 | Validation error |
| -32008 | Record not found |
| -32009 | Method not found |
| -32010 | Rate limit exceeded |
| -32011 | Resource error |
| -32012 | Tool error |

### Error Examples

#### Authentication Error
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32001,
    "message": "Authentication failed"
  },
  "id": 1
}
```

#### Validation Error
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32007,
    "message": "Validation error: Email format is invalid"
  },
  "id": 1
}
```

#### Rate Limit Error
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32010,
    "message": "Rate limit exceeded. Try again in 60 seconds"
  },
  "id": 1
}
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ODOO_URL` | Odoo server URL | - |
| `ODOO_DB` | Database name | - |
| `ODOO_USERNAME` | Username | - |
| `ODOO_PASSWORD` | Password | - |
| `TIMEOUT` | Request timeout | 30 |

### Configuration File

```json
{
  "odoo_url": "http://localhost:8069",
  "database": "your_db",
  "username": "your_user",
  "api_key": "your_password",
  "protocol": "jsonrpc",
  "connection_type": "streamable_http",
  "pool_size": 10,
  "cache_ttl": 300,
  "rate_limit_per_minute": 60,
  "pii_masking": true,
  "audit_logging": true,
  "implicit_domains": true,
  "http": {
    "host": "0.0.0.0",
    "port": 8080,
    "streamable": true
  },
  "logging": {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  }
}
```

## 📈 Performance Considerations

### Caching

- Read operations are automatically cached
- Cache TTL is configurable per operation type
- Schema information is cached with versioning
- Cache can be invalidated manually

### Rate Limiting

- Default: 60 requests per minute
- Burst protection: 100 requests
- Per-IP and per-user limits
- Automatic retry with backoff

### Connection Pooling

- Default pool size: 10 connections
- Automatic health checks
- Connection reuse for performance
- Graceful degradation under load

## 🔒 Security

### Global Authentication

- Single authentication context for all operations
- No user impersonation required
- Secure credential management
- Session-based authentication

### PII Protection

- Automatic field detection and masking
- Configurable masking patterns
- Audit logging for compliance
- Field-level access control

### Input Validation

- Domain expression validation
- Parameter type checking
- SQL injection prevention
- XSS protection

## 📝 Examples

### Complete Workflow Example

```bash
# 1. Get schema information
odoo.schema.models

# 2. Get model fields
odoo.schema.fields --model res.partner

# 3. Search for records
odoo.search_read --model res.partner --domain '{"and": [["active", "=", true]]}'

# 4. Create a new record
odoo.create --model res.partner --values '{"name": "New Partner", "email": "new@example.com"}'

# 5. Get next steps for a record
odoo.actions.next_steps --model res.partner --record-id 123

# 6. Execute an action
odoo.actions.call --model res.partner --record-id 123 --method action_send_email
```

### Python Client Example

```python
import httpx
import json

async def call_odoo_tool(tool_name, arguments):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8080/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "call_tool",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                },
                "id": 1
            }
        )
        return response.json()

# Usage
result = await call_odoo_tool("odoo.search_read", {
    "model": "res.partner",
    "domain_json": {"and": [["active", "=", true]]},
    "limit": 10
})
```

---

For more information, see the [README](README_REFACTORED.md) and [Configuration Guide](CONFIGURATION.md).
