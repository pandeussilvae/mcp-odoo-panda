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
COPY README.md ./
COPY LICENSE ./
COPY odoo_mcp/config/config.json ./odoo_mcp/config/

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -e .[caching] && \
    pip install \
    fastmcp \
    aiohttp \
    httpx \
    pydantic \
    cachetools \
    pytest \
    pytest-asyncio \
    flake8 \
    mypy

# Copy application source code
COPY ./odoo_mcp ./odoo_mcp

# Create directories for logs and config
RUN mkdir -p /app/logs /app/config && \
    chmod 777 /app/logs /app/config

# Set default environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PROTOCOL=xmlrpc \
    CONNECTION_TYPE=streamable_http \
    LOGGING_LEVEL=INFO \
    ODOO_URL=http://odoo:8069 \
    ODOO_DB=odoo \
    ODOO_USER=admin \
    ODOO_PASSWORD=admin \
    POOL_SIZE=5 \
    TIMEOUT=30 \
    SESSION_TIMEOUT_MINUTES=60 \
    REQUESTS_PER_MINUTE=60 \
    RATE_LIMIT_MAX_WAIT_SECONDS=30

# Command to run the application
CMD ["python", "-m", "odoo_mcp.core.mcp_server"]

# Note: Odoo configurations (URL, credentials) can be overridden via environment variables:
# - ODOO_URL
# - ODOO_DB
# - ODOO_USER
# - ODOO_PASSWORD
# - PROTOCOL
# - CONNECTION_TYPE
# - LOGGING_LEVEL
# - POOL_SIZE
# - TIMEOUT
# - SESSION_TIMEOUT_MINUTES
# - REQUESTS_PER_MINUTE
# - RATE_LIMIT_MAX_WAIT_SECONDS
