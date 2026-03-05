"""
Connection Pool implementation for Odoo.
This module provides connection pooling functionality for Odoo API connections.
"""

import asyncio
import logging
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple, Type, Union

from odoo_mcp.core.base_handler import BaseOdooHandler
from odoo_mcp.error_handling.exceptions import (
    AuthError,
    ConfigurationError,
    ConnectionError,
    NetworkError,
    OdooMCPError,
    OdooRecordNotFoundError,
    OdooValidationError,
    PoolTimeoutError,
    ProtocolError,
    SessionError,
)

logger = logging.getLogger(__name__)

# Global connection pool instance
_connection_pool = None


def initialize_connection_pool(
    config: Dict[str, Any], handler_factory: callable
) -> None:
    """
    Initialize the global connection pool.

    Args:
        config: The server configuration dictionary
        handler_factory: The handler factory function to use

    Raises:
        ConfigurationError: If the pool is already initialized
    """
    global _connection_pool
    if _connection_pool is not None:
        raise ConfigurationError("Connection pool is already initialized")

    _connection_pool = ConnectionPool(config, handler_factory)
    logger.info("Connection pool initialized successfully")


def get_connection_pool() -> "ConnectionPool":
    """
    Get the global connection pool instance.

    Returns:
        ConnectionPool: The global connection pool instance

    Raises:
        ConfigurationError: If the pool is not initialized
    """
    if _connection_pool is None:
        raise ConfigurationError("Connection pool is not initialized")
    return _connection_pool


class ConnectionWrapper:
    """
    Wrapper for a connection that manages its lifecycle and usage state.
    """

    def __init__(self, connection: BaseOdooHandler):
        self.connection = connection
        self.in_use = False
        self.last_used = asyncio.get_event_loop().time()

    async def __aenter__(self):
        self.in_use = True
        self.last_used = asyncio.get_event_loop().time()
        return self.connection

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.in_use = False
        self.last_used = asyncio.get_event_loop().time()


class ConnectionPool:
    """
    Manages a pool of connections to Odoo.
    """

    def __init__(self, config: Dict[str, Any], handler_factory: callable):
        """
        Initialize the connection pool.

        Args:
            config: The server configuration dictionary
            handler_factory: The handler factory function to use
        """
        logger.info(f"Initializing connection pool with config: {config}")
        self.config = config.copy()  # Make a copy of the config to avoid modifying the original
        self.handler_factory = handler_factory
        self.max_size = config.get("max_connections", 10)
        self.timeout = config.get("connection_timeout", 30)
        self.connections: List[ConnectionWrapper] = []
        self.health_check_interval = config.get("health_check_interval", 300)  # 5 minutes
        self._lock = asyncio.Lock()
        self._cleanup_task = None
        logger.info(f"Connection pool initialized with max_size={self.max_size}, timeout={self.timeout}")

    async def start(self):
        """Start the connection pool and health check task."""
        self._cleanup_task = asyncio.create_task(self._health_check_loop())
        logger.info("Connection pool started with health check task")

    async def stop(self):
        """Stop the connection pool and cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        await self.close_all()
        logger.info("Connection pool stopped")

    @asynccontextmanager
    async def get_connection(self):
        """
        Get a connection from the pool as an async context manager.
        Yields the underlying handler (BaseOdooHandler). Connection is released on exit.

        Usage:
            async with pool.get_connection() as connection:
                result = await connection.execute_kw(...)

        Raises:
            PoolTimeoutError: If no connection is available within the timeout
            NetworkError: If creating a new connection fails
        """
        wrapper = None
        async with self._lock:
            # Try to find an available connection
            for conn in self.connections:
                if not conn.in_use:
                    conn.in_use = True
                    logger.debug("Reusing existing connection from pool")
                    wrapper = conn
                    break

            if wrapper is None and len(self.connections) < self.max_size:
                try:
                    logger.info("Creating new connection with config: %s", self.config)
                    handler = self.handler_factory(self.config.get("protocol", "xmlrpc"), self.config)
                    wrapper = ConnectionWrapper(handler)
                    self.connections.append(wrapper)
                    wrapper.in_use = True
                    logger.info("Created new connection, pool size now %s", len(self.connections))
                except Exception as e:
                    logger.error("Error creating new connection: %s", e)
                    raise NetworkError(f"Failed to create new connection: {e}") from e

            if wrapper is None:
                logger.warning("Connection pool at max size, waiting for available connection")
                raise PoolTimeoutError("No connections available in pool")

        try:
            yield wrapper.connection
        finally:
            await self.release_connection(wrapper.connection)

    async def release_connection(self, connection: BaseOdooHandler):
        """
        Release a connection back to the pool.

        Args:
            connection: The connection to release
        """
        async with self._lock:
            for wrapper in self.connections:
                if wrapper.connection == connection:
                    wrapper.in_use = False
                    wrapper.last_used = asyncio.get_event_loop().time()
                    break

    async def close_all(self):
        """Close all connections in the pool."""
        async with self._lock:
            for wrapper in self.connections:
                try:
                    await wrapper.connection.cleanup()
                except Exception as e:
                    logger.error(f"Error closing connection: {e}")
            self.connections.clear()

    async def _health_check_loop(self):
        """Periodically check connection health and cleanup stale connections."""
        while True:
            try:
                await asyncio.sleep(self.health_check_interval)
                async with self._lock:
                    current_time = asyncio.get_event_loop().time()
                    for wrapper in self.connections[:]:  # Copy list to allow modification during iteration
                        if not wrapper.in_use and (current_time - wrapper.last_used) > self.health_check_interval:
                            try:
                                if hasattr(wrapper.connection, "close"):
                                    await wrapper.connection.close()
                                self.connections.remove(wrapper)
                                logger.debug("Removed stale connection from pool")
                            except Exception as e:
                                logger.error(f"Error during connection cleanup: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")
                await asyncio.sleep(60)  # Wait a minute before retrying on error

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: List[Any],
        kwargs: Dict[str, Any],
        uid: Optional[int] = None,
        password: Optional[str] = None,
    ) -> Any:
        """
        Execute a method on an Odoo model using a connection from the pool.

        Args:
            model: The Odoo model name
            method: The method to call
            args: Positional arguments for the method
            kwargs: Keyword arguments for the method
            uid: Optional user ID for authentication
            password: Optional password for authentication

        Returns:
            Any: The result of the method call

        Raises:
            NetworkError: If the execution fails
        """
        try:
            async with self.get_connection() as connection:
                return await connection.execute_kw(
                    model=model, method=method, args=args, kwargs=kwargs, uid=uid, password=password
                )
        except Exception as e:
            raise NetworkError(f"Failed to execute {method} on {model}: {str(e)}")

    async def close(self):
        """Close all connections in the pool."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Close all connections in pool
        await self.close_all()

        logger.info("Connection pool closed")
