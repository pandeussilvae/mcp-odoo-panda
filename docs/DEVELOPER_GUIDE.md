# 🛠️ Developer Guide - MCP Odoo Server

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Development Setup](#development-setup)
3. [Code Organization](#code-organization)
4. [Adding New Features](#adding-new-features)
5. [Testing Guidelines](#testing-guidelines)
6. [Performance Optimization](#performance-optimization)
7. [Security Considerations](#security-considerations)
8. [Deployment](#deployment)

## 🏗️ Architecture Overview

### Design Principles

The refactored MCP Odoo Server follows these key design principles:

1. **Separation of Concerns**: Each module has a single responsibility
2. **Factory Pattern**: Protocol handlers are created via factory
3. **Dependency Injection**: Components receive dependencies rather than creating them
4. **Async/Await**: Full async support for high performance
5. **Error Handling**: Comprehensive error handling with custom exceptions
6. **Type Safety**: Complete type hints for better IDE support

### Core Components

```
odoo_mcp/
├── core/                    # Core server components
│   ├── base_handler.py     # Base handler with common functionality
│   ├── handler_factory.py  # Factory for creating handlers
│   ├── xmlrpc_handler.py   # XML-RPC implementation
│   ├── jsonrpc_handler.py  # JSON-RPC implementation
│   ├── connection_pool.py  # Connection pooling
│   ├── authenticator.py    # Authentication management
│   ├── session_manager.py  # Session management
│   ├── resource_manager.py # Resource management
│   └── mcp_server.py      # Main server implementation
├── authentication/         # Authentication components
├── error_handling/         # Error handling and exceptions
├── performance/           # Caching and performance
├── security/              # Security and rate limiting
├── tools/                 # ORM tools and utilities
└── config/               # Configuration management
```

## 🚀 Development Setup

### Prerequisites

- Python 3.9+
- Poetry or pip
- Git
- Docker (optional)

### Installation

```bash
# Clone the repository
git clone https://github.com/pandeussilvae/mcp-odoo-panda.git
cd mcp-odoo-panda

# Install with development dependencies
pip install -e ".[dev]"

# Or using Poetry
poetry install
```

### Development Tools

```bash
# Install pre-commit hooks
pre-commit install

# Run linting
black odoo_mcp/
flake8 odoo_mcp/
mypy odoo_mcp/

# Run tests
pytest tests/ -v --cov=odoo_mcp
```

### IDE Configuration

#### VS Code

Create `.vscode/settings.json`:

```json
{
  "python.defaultInterpreterPath": "./venv/bin/python",
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": false,
  "python.linting.flake8Enabled": true,
  "python.linting.mypyEnabled": true,
  "python.formatting.provider": "black",
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["tests/"]
}
```

## 📁 Code Organization

### Module Structure

Each module follows a consistent structure:

```
module_name/
├── __init__.py           # Module initialization
├── main_class.py         # Main implementation
├── exceptions.py         # Module-specific exceptions
├── utils.py             # Utility functions
├── tests/               # Module tests
│   ├── test_main.py
│   └── test_utils.py
└── README.md            # Module documentation
```

### Import Organization

Follow this import order:

```python
# Standard library imports
import asyncio
import logging
from typing import Dict, List, Optional

# Third-party imports
import httpx
from pydantic import BaseModel

# Local imports
from odoo_mcp.core.base_handler import BaseOdooHandler
from odoo_mcp.error_handling.exceptions import ConfigurationError
```

### Type Hints

Always use type hints:

```python
async def process_data(
    data: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Process data with optional configuration."""
    pass
```

### Documentation

Use Google-style docstrings:

```python
def example_function(param1: str, param2: int = 10) -> bool:
    """
    Brief description of the function.
    
    Longer description if needed, explaining the purpose,
    behavior, and any important details.
    
    Args:
        param1: Description of param1
        param2: Description of param2 (default: 10)
        
    Returns:
        Description of return value
        
    Raises:
        ValueError: When param1 is invalid
        ConfigurationError: When configuration is missing
        
    Example:
        >>> result = example_function("test", 20)
        >>> print(result)
        True
    """
    pass
```

## 🔧 Adding New Features

### Adding a New Protocol Handler

1. **Create the handler class:**

```python
# odoo_mcp/core/grpc_handler.py
from odoo_mcp.core.base_handler import BaseOdooHandler

class GRPCHandler(BaseOdooHandler):
    """GRPC handler implementation."""
    
    async def _perform_authentication(self, username: str, password: str, database: str):
        # Implement GRPC authentication
        pass
    
    async def call(self, service: str, method: str, args: list):
        # Implement GRPC calls
        pass
    
    async def execute_kw(self, model: str, method: str, args: List = None, kwargs: Dict = None):
        # Implement model operations
        pass
```

2. **Register with the factory:**

```python
# odoo_mcp/core/handler_factory.py
from odoo_mcp.core.grpc_handler import GRPCHandler

class HandlerFactory:
    _handler_registry: Dict[str, Type[BaseOdooHandler]] = {
        "xmlrpc": XMLRPCHandler,
        "jsonrpc": JSONRPCHandler,
        "grpc": GRPCHandler,  # Add new handler
    }
```

3. **Add tests:**

```python
# tests/test_grpc_handler.py
import pytest
from odoo_mcp.core.grpc_handler import GRPCHandler

@pytest.mark.asyncio
async def test_grpc_handler_creation():
    config = {"protocol": "grpc", "odoo_url": "grpc://localhost:50051"}
    handler = GRPCHandler(config)
    assert handler.protocol == "grpc"
```

### Adding New ORM Tools

1. **Define the tool:**

```python
# odoo_mcp/tools/custom_tools.py
from odoo_mcp.tools.orm_tools import ORMTools

class CustomORMTools(ORMTools):
    async def custom_operation(self, model: str, **kwargs):
        """Custom operation implementation."""
        # Implementation here
        pass
```

2. **Register the tool:**

```python
# odoo_mcp/core/mcp_server.py
def _register_tools_and_prompts(self):
    # Register custom tool
    self.register_tool(
        Tool(
            name="odoo.custom_operation",
            description="Custom operation tool",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "param": {"type": "string"}
                },
                "required": ["model"]
            }
        )
    )
```

### Adding New Error Types

1. **Define the exception:**

```python
# odoo_mcp/error_handling/exceptions.py
class CustomError(OdooMCPError):
    """Custom error for specific scenarios."""
    
    def __init__(
        self,
        message: str = "Custom error occurred",
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(message, code=-32013, original_exception=original_exception)
```

2. **Use in your code:**

```python
from odoo_mcp.error_handling.exceptions import CustomError

def validate_input(data):
    if not data:
        raise CustomError("Input data is required")
```

## 🧪 Testing Guidelines

### Test Structure

```
tests/
├── unit/                  # Unit tests
│   ├── test_handlers.py
│   ├── test_pool.py
│   └── test_tools.py
├── integration/          # Integration tests
│   ├── test_server.py
│   └── test_workflows.py
├── performance/          # Performance tests
│   ├── test_load.py
│   └── test_stress.py
├── fixtures/             # Test fixtures
│   ├── config.json
│   └── sample_data.py
└── conftest.py          # Pytest configuration
```

### Writing Tests

```python
# tests/unit/test_handlers.py
import pytest
from unittest.mock import AsyncMock, patch
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler

@pytest.fixture
def xmlrpc_config():
    return {
        "odoo_url": "http://localhost:8069",
        "database": "test_db",
        "username": "test_user",
        "api_key": "test_pass"
    }

@pytest.mark.asyncio
async def test_xmlrpc_handler_creation(xmlrpc_config):
    """Test XMLRPC handler creation."""
    with patch('xmlrpc.client.ServerProxy'):
        handler = XMLRPCHandler(xmlrpc_config)
        assert handler.odoo_url == xmlrpc_config["odoo_url"]

@pytest.mark.asyncio
async def test_authentication_success(xmlrpc_config):
    """Test successful authentication."""
    with patch('xmlrpc.client.ServerProxy') as mock_proxy:
        mock_proxy.return_value.authenticate.return_value = 123
        handler = XMLRPCHandler(xmlrpc_config)
        
        result = await handler._perform_authentication(
            "user", "pass", "db"
        )
        assert result == 123
```

### Test Categories

#### Unit Tests
- Test individual functions and methods
- Mock external dependencies
- Focus on logic and edge cases
- Aim for 100% code coverage

#### Integration Tests
- Test component interactions
- Use real dependencies where possible
- Test complete workflows
- Verify error handling

#### Performance Tests
- Measure response times
- Test under load
- Monitor memory usage
- Benchmark improvements

### Running Tests

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/unit/test_handlers.py

# Run with coverage
pytest --cov=odoo_mcp tests/

# Run performance tests
pytest tests/performance/ -v

# Run with specific markers
pytest -m "not slow" tests/
```

## ⚡ Performance Optimization

### Profiling

```python
# Use cProfile for profiling
import cProfile
import pstats

def profile_function():
    # Your code here
    pass

cProfile.run('profile_function()', 'profile_stats')
stats = pstats.Stats('profile_stats')
stats.sort_stats('cumulative').print_stats(10)
```

### Async Optimization

```python
# Good: Concurrent operations
async def fetch_multiple_records(ids):
    tasks = [fetch_record(id) for id in ids]
    return await asyncio.gather(*tasks)

# Bad: Sequential operations
async def fetch_multiple_records_slow(ids):
    results = []
    for id in ids:
        result = await fetch_record(id)
        results.append(result)
    return results
```

### Memory Management

```python
# Use context managers for resources
async def process_data():
    async with get_connection() as conn:
        # Process data
        pass
    # Connection automatically closed

# Clean up large objects
def process_large_dataset(data):
    try:
        # Process data
        result = heavy_computation(data)
        return result
    finally:
        # Clean up
        del data
        gc.collect()
```

### Caching Strategies

```python
from functools import lru_cache
from odoo_mcp.performance.caching import cache_result

@cache_result(ttl=300)  # 5 minutes
async def expensive_operation(param):
    # Expensive computation
    return result

@lru_cache(maxsize=128)
def parse_domain(domain_str):
    # Parse domain string
    return parsed_domain
```

## 🔒 Security Considerations

### Input Validation

```python
from pydantic import BaseModel, validator

class RequestModel(BaseModel):
    model: str
    domain: Optional[Dict] = None
    
    @validator('model')
    def validate_model_name(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError('Model name must be a non-empty string')
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', v):
            raise ValueError('Invalid model name format')
        return v
    
    @validator('domain')
    def validate_domain(cls, v):
        if v is not None:
            # Validate domain structure
            validate_domain_structure(v)
        return v
```

### Authentication Security

```python
import hashlib
import secrets

def generate_session_token():
    """Generate cryptographically secure session token."""
    return secrets.token_urlsafe(32)

def hash_password(password: str, salt: str) -> str:
    """Hash password with salt."""
    return hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()

def verify_password(password: str, hashed: str, salt: str) -> bool:
    """Verify password against hash."""
    return hash_password(password, salt) == hashed
```

### Rate Limiting

```python
from odoo_mcp.security.utils import RateLimiter

class SecureHandler:
    def __init__(self):
        self.rate_limiter = RateLimiter(
            requests_per_minute=60,
            max_wait_seconds=30
        )
    
    async def handle_request(self, request):
        # Check rate limit
        if not await self.rate_limiter.allow_request(request.client_ip):
            raise RateLimitError("Rate limit exceeded")
        
        # Process request
        return await self.process_request(request)
```

### Data Sanitization

```python
import html
import re

def sanitize_input(data: str) -> str:
    """Sanitize user input."""
    # Remove potentially dangerous characters
    data = re.sub(r'[<>"\']', '', data)
    # HTML escape
    data = html.escape(data)
    # Limit length
    return data[:1000]

def validate_domain_structure(domain):
    """Validate domain structure for security."""
    # Check for dangerous operations
    dangerous_ops = ['exec', 'eval', 'import']
    domain_str = str(domain)
    
    for op in dangerous_ops:
        if op in domain_str.lower():
            raise ValueError(f"Dangerous operation detected: {op}")
```

## 🚀 Deployment

### Docker Configuration

```dockerfile
# Dockerfile
FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run application
CMD ["python", "-m", "odoo_mcp.server", "--config", "config.json"]
```

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  mcp-server:
    build: .
    ports:
      - "8080:8080"
    environment:
      - ODOO_URL=http://odoo:8069
      - ODOO_DB=production
      - ODOO_USERNAME=admin
      - ODOO_PASSWORD=admin
    volumes:
      - ./config:/app/config
      - ./logs:/app/logs
    depends_on:
      - odoo
    restart: unless-stopped

  odoo:
    image: odoo:18.0
    ports:
      - "8069:8069"
    environment:
      - HOST=postgres
      - USER=odoo
      - PASSWORD=odoo
    depends_on:
      - postgres

  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=postgres
      - POSTGRES_USER=odoo
      - POSTGRES_PASSWORD=odoo
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

### Kubernetes Deployment

```yaml
# k8s-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-server
spec:
  replicas: 3
  selector:
    matchLabels:
      app: mcp-server
  template:
    metadata:
      labels:
        app: mcp-server
    spec:
      containers:
      - name: mcp-server
        image: mcp-server:latest
        ports:
        - containerPort: 8080
        env:
        - name: ODOO_URL
          value: "http://odoo-service:8069"
        - name: ODOO_DB
          valueFrom:
            secretKeyRef:
              name: odoo-secrets
              key: database
        - name: ODOO_USERNAME
          valueFrom:
            secretKeyRef:
              name: odoo-secrets
              key: username
        - name: ODOO_PASSWORD
          valueFrom:
            secretKeyRef:
              name: odoo-secrets
              key: password
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
```

### Monitoring

```python
# monitoring.py
from prometheus_client import Counter, Histogram, Gauge
import time

# Metrics
REQUEST_COUNT = Counter('mcp_requests_total', 'Total requests', ['method', 'endpoint'])
REQUEST_DURATION = Histogram('mcp_request_duration_seconds', 'Request duration')
ACTIVE_CONNECTIONS = Gauge('mcp_active_connections', 'Active connections')

class MetricsMiddleware:
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, request, handler):
        start_time = time.time()
        
        try:
            response = await handler(request)
            REQUEST_COUNT.labels(
                method=request.method,
                endpoint=request.path
            ).inc()
            return response
        finally:
            REQUEST_DURATION.observe(time.time() - start_time)
```

### Logging Configuration

```python
# logging_config.py
import logging
import logging.handlers
from pythonjsonlogger import jsonlogger

def setup_logging(level='INFO', log_file=None):
    """Setup structured logging."""
    
    # Create formatter
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(name)s %(levelname)s %(message)s'
    )
    
    # Setup handlers
    handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)
    
    # File handler
    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10*1024*1024, backupCount=5
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        handlers=handlers
    )
```

## 📚 Additional Resources

- [API Reference](API_REFERENCE.md)
- [Configuration Guide](CONFIGURATION.md)
- [Performance Tuning](PERFORMANCE.md)
- [Security Best Practices](SECURITY.md)
- [Troubleshooting Guide](TROUBLESHOOTING.md)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Run the test suite
6. Submit a pull request

### Code Review Checklist

- [ ] Code follows style guidelines
- [ ] Type hints are complete
- [ ] Documentation is updated
- [ ] Tests are added/updated
- [ ] Performance impact is considered
- [ ] Security implications are reviewed
- [ ] Backward compatibility is maintained

---

For questions or support, please open an issue or contact the development team.
