"""
Connection Pool implementation for Odoo.
This module provides connection pooling functionality for Odoo API connections.
"""

import logging
import asyncio
from typing import Dict, Any, Type, Optional, Union, List, Tuple, Set
from datetime import datetime, timedelta
from collections import deque
from contextlib import asynccontextmanager

from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler
from odoo_mcp.core.jsonrpc_handler import JSONRPCHandler
from odoo_mcp.error_handling.exceptions import (
    OdooMCPError, ConfigurationError, NetworkError, AuthError,
    ProtocolError, ConnectionError, SessionError,
    OdooValidationError, OdooRecordNotFoundError, PoolTimeoutError
)

logger = logging.getLogger(__name__)

# Global connection pool instance
_connection_pool = None

def initialize_connection_pool(config: Dict[str, Any], handler_class: Type[Union[XMLRPCHandler, JSONRPCHandler]]) -> None:
    """
    Initialize the global connection pool.

    Args:
        config: The server configuration dictionary
        handler_class: The handler class to use (XMLRPCHandler or JSONRPCHandler)

    Raises:
        ConfigurationError: If the pool is already initialized
    """
    global _connection_pool
    if _connection_pool is not None:
        raise ConfigurationError("Connection pool is already initialized")
    
    _connection_pool = ConnectionPool(config, handler_class)
    logger.info("Connection pool initialized successfully")

def get_connection_pool() -> 'ConnectionPool':
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
    def __init__(self, connection: Union[XMLRPCHandler, JSONRPCHandler]):
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
    def __init__(self, config: Dict[str, Any], handler_class: Type[Union[XMLRPCHandler, JSONRPCHandler]]):
        """
        Initialize the connection pool.

        Args:
            config: The server configuration dictionary
            handler_class: The handler class to use (XMLRPCHandler or JSONRPCHandler)
        """
        self.config = config
        self.handler_class = handler_class
        self.max_size = config.get('max_connections', 10)
        self.timeout = config.get('connection_timeout', 30)
        self.connections: List[ConnectionWrapper] = []
        self.health_check_interval = config.get('health_check_interval', 300)  # 5 minutes
        self._lock = asyncio.Lock()
        self._cleanup_task = None

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
        Get a connection from the pool.

        Yields:
            Union[XMLRPCHandler, JSONRPCHandler]: A connection handler

        Raises:
            PoolTimeoutError: If no connection is available within the timeout
            ConnectionError: If creating a new connection fails
        """
        async with self._lock:
            # Try to find an available connection
            for conn in self.connections:
                if not conn.in_use:
                    try:
                        async with conn as connection:
                            yield connection
                        return
                    except Exception as e:
                        logger.error(f"Error using existing connection: {e}")
                        self.connections.remove(conn)
                        continue

            # If we haven't reached max size, create a new connection
            if len(self.connections) < self.max_size:
                try:
                    connection = self.handler_class(self.config)
                    wrapper = ConnectionWrapper(connection)
                    self.connections.append(wrapper)
                    async with wrapper as conn:
                        yield conn
                    return
                except Exception as e:
                    logger.error(f"Error creating new connection: {e}")
                    raise ConnectionError(f"Failed to create new connection: {e}")

            # If we're at max size, wait for a connection to become available
            try:
                async with asyncio.timeout(self.timeout):
                    while True:
                        for conn in self.connections:
                            if not conn.in_use:
                                try:
                                    async with conn as connection:
                                        yield connection
                                    return
                                except Exception as e:
                                    logger.error(f"Error using existing connection: {e}")
                                    self.connections.remove(conn)
                                    continue
                        await asyncio.sleep(0.1)
            except asyncio.TimeoutError:
                raise PoolTimeoutError(f"No connection available within {self.timeout} seconds")

    async def release_connection(self, connection: Union[XMLRPCHandler, JSONRPCHandler]):
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
                    if hasattr(wrapper.connection, 'close'):
                        await wrapper.connection.close()
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
                                if hasattr(wrapper.connection, 'close'):
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
        password: Optional[str] = None
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
        handler = None
        try:
            async with await self.get_connection() as handler:
                return await handler.execute_kw(
                    model=model,
                    method=method,
                    args=args,
                    kwargs=kwargs,
                    uid=uid,
                    password=password
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