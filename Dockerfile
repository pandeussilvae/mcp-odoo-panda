# Use Python 3.11 slim image as base
FROM python:3.11-slim-bookworm

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy configuration files
COPY pyproject.toml ./
COPY LICENSE ./
# Ship example config as default; override via env (ODOO_*) or mounted volume
COPY odoo_mcp/config/config.example.yaml ./odoo_mcp/config/config.yaml

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -e .[caching] && \
    pip install \
    "mcp>=2.1.1,<3" \
    aiohttp \
    httpx \
    pydantic \
    cachetools \
    uvicorn \
    starlette \
    pytest \
    pytest-asyncio \
    flake8 \
    mypy

# Copy application source code
COPY ./odoo_mcp ./odoo_mcp

# Create directories for logs and config
RUN mkdir -p /app/logs /app/config && \
    chmod 777 /app/logs /app/config

# Set default environment variables (non-sensitive defaults)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PROTOCOL=xmlrpc \
    CONNECTION_TYPE=mcp_2026_07_28 \
    LOGGING_LEVEL=INFO \
    ODOO_URL=http://odoo:8069 \
    ODOO_DB=odoo \
    ODOO_USER=admin \
    POOL_SIZE=5 \
    TIMEOUT=30 \
    SESSION_TIMEOUT_MINUTES=60 \
    REQUESTS_PER_MINUTE=60 \
    RATE_LIMIT_MAX_WAIT_SECONDS=30

# DEV-ONLY: ODOO_USER=admin above is a local-lab default.
# Note: ODOO_PASSWORD should be set via environment variable or secrets
# Never hardcode passwords in Docker images

# Command to run the application
CMD ["python", "-m", "odoo_mcp.core.mcp_server"]

# Note: Odoo configurations can be overridden via environment variables:
# - ODOO_URL (required)
# - ODOO_DB (required)
# - ODOO_USER (required)
# - ODOO_PASSWORD (required - must be set at runtime for security)
# - PROTOCOL (xmlrpc/jsonrpc)
# - CONNECTION_TYPE (stdio/streamable_http/sse)
# - LOGGING_LEVEL (DEBUG/INFO/WARNING/ERROR)
# - POOL_SIZE (connection pool size)
# - TIMEOUT (request timeout)
# - SESSION_TIMEOUT_MINUTES (session duration)
# - REQUESTS_PER_MINUTE (rate limiting)
# - RATE_LIMIT_MAX_WAIT_SECONDS (rate limit wait time)
#
# Example usage:
# docker run -e ODOO_PASSWORD=your_password -e ODOO_URL=http://your-odoo:8069 mcp-odoo-panda
