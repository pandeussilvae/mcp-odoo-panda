# Odoo MCP Server

<div align="center">
  <img src="assets/Odoo MCP Server.png" alt="Odoo MCP Server Logo" width="100%"/> 
</div>

## Developed by

This module was developed by [Paolo Nugnes](https://github.com/pandeussilvae) and [TechLab](https://www.techlab.it).

TechLab is a company specialized in custom software development and enterprise system integration. Visit our website [www.techlab.it](https://www.techlab.it) for more information about our services.

## Overview

The Odoo MCP Server is a standardized interface for interacting with Odoo instances through the MCP (Model Context Protocol). It provides support for:

- **Communication Protocols**:
  - stdio: Direct communication via stdin/stdout
  - streamable_http: HTTP communication with streaming response support

- **Resource Management**:
  - Odoo records (single and list)
  - Binary fields
  - Real-time updates

- **Tools**:
  - Search and read records
  - Create and update records
  - Delete records
  - Call custom methods

- **Security**:
  - Authentication and session management
  - Rate limiting
  - CORS for streamable_http connections

## System Requirements

### Hardware Requirements
- CPU: 2+ cores
- RAM: 4GB minimum (8GB recommended)
- Disk Space: 1GB minimum

### Software Requirements
- Python 3.9+
- Odoo 15.0+
  - Required modules: base, web, bus
  - Database configured with admin user
- Docker (optional)

### Network Requirements
- Port 8069 (Odoo)
- Port 8080 (streamable_http, optional)
- Port 5432 (PostgreSQL, if local)

### Security Requirements
- SSL certificate for HTTPS (production)
- Configured firewall
- VPN access (optional)

## Installation

### Direct Installation

```bash
# Clone the repository
git clone https://github.com/pandeussilvae/mcp-odoo-panda.git
cd mcp-odoo-panda

# Install dependencies
pip install .

# To install with caching support
pip install .[caching]

# To install with development tools
pip install .[dev]

# Copy the example configuration file
cp odoo_mcp/config/config.example.json odoo_mcp/config/config.json

# Edit config.json with your settings
# nano odoo_mcp/config/config.json
```

### Docker Installation

```bash
# Clone the repository
git clone https://github.com/pandeussilvae/mcp-odoo-panda.git
cd mcp-odoo-panda

# Start with Docker Compose
docker-compose up -d
```

## Configuration

The server can be configured through a JSON file. Several configuration templates are available:

- `config.example.json`: Main template to copy and modify
- `config.dev.json`: Development environment template (optional)
- `config.prod.json`: Production environment template (optional)

To get started:

```bash
# Copy the example configuration file
cp odoo_mcp/config/config.example.json odoo_mcp/config/config.json

# Edit config.json with your settings
# nano odoo_mcp/config/config.json
```

### Selecting the Connection Type

The Odoo MCP server supports several connection types, configurable via the `connection_type` field in `config.json`. Supported values:

- `stdio`: Default, direct communication via stdin/stdout
- `streamable_http`: HTTP with streaming/chunked responses (real-time data flows)
- `http`: Classic HTTP POST (stateless, single request/response)

Example configuration:
```json
{
  "connection_type": "streamable_http",  // or "http" or "stdio"
  "http": {
    "host": "0.0.0.0",
    "port": 8080
  }
}
```

- Use `streamable_http` for real-time streaming over HTTP (endpoint: `POST /mcp`)
- Use `http` for classic REST requests (endpoint: `POST /mcp`)
- Use `stdio` for direct communication (default)

Example of complete configuration:

```json
{
    "mcpServers": {
        "mcp-odoo-panda": {
            "command": "/usr/bin/python3",
            "args": [
                "--directory",
                "/path/to/mcp-odoo-panda",
                "mcp/server.py",
                "--config",
                "/path/to/mcp-odoo-panda/odoo_mcp/config/config.json"
            ]
        }
    },
    "odoo_url": "http://localhost:8069",
    "database": "my_database",
    "username": "admin",
    "api_key": "admin",
    "protocol": "xmlrpc",
    "connection_type": "streamable_http",
    "requests_per_minute": 120,
    "rate_limit_max_wait_seconds": 5,
    "pool_size": 5,
    "timeout": 30,
    "session_timeout_minutes": 60,
    "http": {
        "host": "0.0.0.0",
        "port": 8080,
        "streamable": true
    },
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        "handlers": [
            {
                "type": "StreamHandler",
                "level": "INFO"
            },
            {
                "type": "FileHandler",
                "filename": "server.log",
                "level": "DEBUG"
            }
        ]
    }
}
```

## Starting the Server

The server can be started in two modes: stdio (default) and streamable_http. The configuration file is optional and, if not specified, the server will automatically look for the file in `odoo_mcp/config/config.json`.

### stdio Mode (default)

```bash
# Start the server in stdio mode without specifying the configuration file
python -m odoo_mcp.server

# Start the server in stdio mode with a specific configuration file
python -m odoo_mcp.server /path/to/config.json
```

### streamable_http Mode

```bash
# Start the server in streamable_http mode without specifying the configuration file
python -m odoo_mcp.server streamable_http

# Start the server in streamable_http mode with a specific configuration file
python -m odoo_mcp.server streamable_http /path/to/config.json
```

### HTTP Modes

The Odoo MCP server supports two HTTP modes:

1. **HTTP Streaming Chunked** (`streamable_http`):
   - Endpoint: `POST /mcp`
   - Keeps the connection open and streams data
   - Ideal for real-time data flows
   - Required headers:
     ```
     Content-Type: application/json
     Connection: keep-alive
     ```

2. **Classic HTTP POST** (`http`):
   - Endpoint: `POST /mcp`
   - Handles a single request/response (stateless)
   - Standard REST behavior
   - Required headers:
     ```
     Content-Type: application/json
     ```

3. **Server-Sent Events** (SSE):
   - Endpoint: `GET /sse`
   - Server-push event support
   - Required headers:
     ```
     Accept: text/event-stream
     ```

To configure the HTTP mode, set `connection_type` in `config.json`:
```json
{
  "connection_type": "streamable_http",  // or "http"
  "http": {
    "host": "0.0.0.0",
    "port": 8080
  }
}
```

### Example Calls

1. **HTTP Streaming Chunked**:
```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Connection: keep-alive" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "id": 1}'
```

2. **Classic HTTP POST**:
```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "id": 1}'
```

3. **Server-Sent Events**:
```bash
curl -N http://localhost:8080/sse \
  -H "Accept: text/event-stream"
```

## Server Verification

### stdio Mode

```bash
# Test a request without specifying the configuration file
echo '{"method": "get_resource", "params": {"uri": "odoo://res.partner/1"}}' | python -m odoo_mcp.server

# Test a request with a specific configuration file
echo '{"method": "get_resource", "params": {"uri": "odoo://res.partner/1"}}' | python -m odoo_mcp.server /path/to/config.json
```

### streamable_http Mode

```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Connection: keep-alive" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}'
```

### http Mode (Classic HTTP POST)

```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}'
```

### Server-Sent Events (SSE)

```bash
curl -N http://localhost:8080/sse \
  -H "Accept: text/event-stream"
```

## Usage

### stdio Connection

```python
import asyncio
from mcp import Client

async def main():
    client = Client(connection_type="stdio")
    await client.initialize()
    
    # Example: Read a record
    resource = await client.get_resource("odoo://res.partner/1")
    print(resource.data)

if __name__ == "__main__":
    asyncio.run(main())
```

### streamable_http Connection

```python
import asyncio
from mcp import Client

async def main():
    client = Client(connection_type="streamable_http")
    await client.initialize()
    
    # Example: Read a record
    resource = await client.get_resource("odoo://res.partner/1")
    print(resource.data)

if __name__ == "__main__":
    asyncio.run(main())
```

### Connecting Claude Desktop to the Odoo MCP server (stdio)

To connect Claude Desktop to the Odoo MCP server using the stdio protocol:

1. Make sure the Odoo MCP server is installed and working.
2. Open Claude Desktop settings (Claude menu → Settings → Developer → Edit Config).
3. Add the following configuration to the `mcpServers` section of your `claude_desktop_config.json` file:

```json
{
  "mcpServers": {
    "odoo-mcp": {
      "command": "python",
      "args": [
        "-m",
        "odoo_mcp.server",
        "C:/absolute/path/to/your/config.json"
      ]
    }
  }
}
```
> Replace `C:/absolute/path/to/your/config.json` with the actual path to your configuration file.

4. Save and restart Claude Desktop. You should see the MCP tools available.

**Note:** Claude Desktop only communicates via stdio. Do not use `streamable_http` for connecting with Claude Desktop.

## Documentation

Complete documentation is available in the `docs/` directory:

- `mcp_protocol.md`: MCP protocol documentation
- `odoo_server.md`: Odoo server documentation
- `server_usage.md`: Server usage guide

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is released under the MIT License. See the `LICENSE` file for details.

## Update

### Update from Source
```bash
# Update the repository
git pull origin main

# Reinstall the package
pip install --upgrade .

# Restart the server
systemctl restart odoo-mcp-server
```

### Update with Docker
```bash
# Update images
docker-compose pull

# Restart containers
docker-compose up -d
```

## Uninstallation

### Uninstall from Source
```bash
# Uninstall the package
pip uninstall odoo-mcp-server

# Remove configuration files
rm -rf ~/.odoo-mcp-server
```

### Uninstall with Docker
```bash
# Stop and remove containers
docker-compose down

# Remove images
docker-compose rm -f
```

## Advanced Configuration

### Environment Configuration

#### Development
```json
{
    "protocol": "xmlrpc",
    "connection_type": "stdio",
    "odoo_url": "http://localhost:8069",
    "database": "dev_db",
    "username": "admin",
    "api_key": "admin",
    "logging": {
        "level": "DEBUG",
        "handlers": [
            {
                "type": "FileHandler",
                "filename": "logs/dev.log",
                "level": "DEBUG"
            }
        ]
    }
}
```

#### Production
```json
{
    "protocol": "jsonrpc",
    "connection_type": "streamable_http",
    "odoo_url": "https://odoo.example.com",
    "database": "prod_db",
    "username": "admin",
    "api_key": "your-secure-api-key",
    "http": {
        "host": "0.0.0.0",
        "port": 8080,
        "streamable": true
    },
    "logging": {
        "level": "INFO",
        "handlers": [
            {
                "type": "FileHandler",
                "filename": "logs/prod.log",
                "level": "INFO"
            }
        ]
    }
}
```

### Configuration Backup
```bash
# Backup configuration
cp odoo_mcp/config/config.json odoo_mcp/config/config.json.backup

# Restore configuration
cp odoo_mcp/config/config.json.backup odoo_mcp/config/config.json
```

## Advanced Usage

### Error Handling
```python
from odoo_mcp.error_handling.exceptions import (
    AuthError, NetworkError, ProtocolError
)

try:
    await client.get_resource("odoo://res.partner/1")
except AuthError as e:
    logger.error(f"Authentication error: {e}")
    # Error handling
except NetworkError as e:
    logger.error(f"Network error: {e}")
    # Error handling
except ProtocolError as e:
    logger.error(f"Protocol error: {e}")
    # Error handling
```

### Best Practices

1. **Connection Management**:
   ```python
   async with Client() as client:
       await client.initialize()
       # Operations
   ```

2. **Cache Management**:
   ```python
   # Cache configuration
   cache_config = {
       'enabled': True,
       'ttl': 300,
       'max_size': 1000
   }
   ```

3. **Session Management**:
   ```python
   # Create session
   session = await client.create_session()
   
   # Validate session
   if await client.validate_session(session_id):
       # Operations
   ```

## Troubleshooting

### Common Issues

1. **Connection Error**:
   ```
   ERROR: Could not connect to Odoo server
   ```
   Solution:
   - Verify that Odoo is running on port 8069
   - Check that the firewall allows access to port 8069
   - Verify that the Odoo URL in the configuration file is correct
   - Check that the database is accessible

2. **Authentication Error**:
   ```
   ERROR: Authentication failed
   ```
   Solution:
   - Verify that username and api_key in the configuration file are correct
   - Check that the user has the necessary permissions in the Odoo database
   - Verify that the specified database exists
   - Check that the base, web, and bus modules are installed

3. **Protocol Error**:
   ```
   ERROR: Protocol error
   ```
   Solution:
   - Verify that the specified protocol (xmlrpc/jsonrpc) is supported
   - Check that the Odoo version is compatible (15.0+)
   - Verify that the connection type (stdio/streamable_http) is correct
   - Check the logs for specific error details

4. **Rate Limiting Error**:
   ```
   ERROR: Rate limit exceeded
   ```
   Solution:
   - Increase the `requests_per_minute` value in the configuration file
   - Implement a retry mechanism with backoff
   - Optimize requests to reduce the number of calls

5. **Cache Error**:
   ```
   ERROR: Cache error
   ```
   Solution:
   - Verify that the configured cache type is supported
   - Check that there is sufficient space for the cache
   - Temporarily disable the cache if necessary

### Error Logs

**Important note:** In the current version, the Odoo MCP server can write logs to multiple destinations depending on configuration:

- If the `logging` section in `config.json` includes a `StreamHandler`, logs are written to the **console** (stderr).
- If a `FileHandler` is present, logs are also written to a **file** at the path specified by `filename`.
- If there is no `logging`, logs are written only to stderr (console).

**Example:**
```json
"logging": {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "handlers": [
        {
            "type": "StreamHandler",
            "level": "INFO"
        },
        {
            "type": "FileHandler",
            "filename": "server.log",
            "level": "DEBUG"
        }
    ]
}
```
- In this example, logs go both to the console and to the file `server.log` in the directory where you start the server.
- You can change the log file path by editing the `filename` field (e.g., `"filename": "logs/dev.log"` or an absolute path).

### Support

For technical support:
1. Check the [documentation](docs/)
2. Open an [issue](https://github.com/pandeussilvae/mcp-odoo-panda/issues)
3. Contact [support@techlab.it](mailto:support@techlab.it)

