"""
Connection Pool implementation for Odoo.
This module provides connection pooling functionality for Odoo API connections.
"""

import logging
import asyncio
from typing import Dict, Any, Type, Optional, Union, List
from datetime import datetime, timedelta
from collections import deque

from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler
from odoo_mcp.core.jsonrpc_handler import JSONRPCHandler
from odoo_mcp.error_handling.exceptions import (
    OdooMCPError, ConfigurationError, NetworkError, AuthError
)

logger = logging.getLogger(__name__)

class ConnectionPool:
    """
    Connection pool for managing Odoo API connections.
    Provides connection reuse, automatic cleanup, and error handling.
    """

    def __init__(self, config: Dict[str, Any], handler_class: Type[Union[XMLRPCHandler, JSONRPCHandler]]):
        """
        Initialize the connection pool.

        Args:
            config: Configuration dictionary
            handler_class: The handler class to use (XMLRPCHandler or JSONRPCHandler)
        """
        self.config = config
        self.handler_class = handler_class
        self.pool_size = config.get('pool_size', 5)
        self.max_lifetime = timedelta(minutes=config.get('connection_lifetime_minutes', 30))
        self.cleanup_interval = timedelta(minutes=config.get('cleanup_interval_minutes', 5))
        
        # Connection pool storage
        self._pool: deque = deque(maxlen=self.pool_size)
        self._in_use: Dict[str, Dict[str, Any]] = {}
        
        # Initialize cleanup task
        self._cleanup_task = None
        self._start_cleanup_task()

    def _start_cleanup_task(self):
        """Start the periodic cleanup task."""
        async def cleanup():
            while True:
                try:
                    await self._cleanup_expired_connections()
                except Exception as e:
                    logger.error(f"Error during connection cleanup: {e}")
                await asyncio.sleep(self.cleanup_interval.total_seconds())

        self._cleanup_task = asyncio.create_task(cleanup())

    async def _cleanup_expired_connections(self):
        """Clean up expired connections from the pool."""
        now = datetime.now()
        
        # Clean up expired connections in pool
        while self._pool:
            conn = self._pool[0]
            if now - conn['created_at'] > self.max_lifetime:
                self._pool.popleft()
                try:
                    await conn['handler'].close()
                except Exception as e:
                    logger.error(f"Error closing expired connection: {e}")
            else:
                break

        # Clean up expired connections in use
        expired_keys = [
            key for key, conn in self._in_use.items()
            if now - conn['created_at'] > self.max_lifetime
        ]
        for key in expired_keys:
            conn = self._in_use.pop(key)
            try:
                await conn['handler'].close()
            except Exception as e:
                logger.error(f"Error closing expired in-use connection: {e}")

    async def get_connection(self) -> Union[XMLRPCHandler, JSONRPCHandler]:
        """
        Get a connection from the pool or create a new one.

        Returns:
            Union[XMLRPCHandler, JSONRPCHandler]: A connection handler

        Raises:
            NetworkError: If unable to create or get a connection
        """
        try:
            # Try to get a connection from the pool
            while self._pool:
                conn = self._pool.popleft()
                if datetime.now() - conn['created_at'] <= self.max_lifetime:
                    self._in_use[conn['id']] = conn
                    return conn['handler']
                else:
                    try:
                        await conn['handler'].close()
                    except Exception as e:
                        logger.error(f"Error closing expired connection: {e}")

            # Create a new connection if pool is empty
            handler = self.handler_class(self.config)
            conn_id = str(id(handler))
            conn = {
                'id': conn_id,
                'handler': handler,
                'created_at': datetime.now()
            }
            self._in_use[conn_id] = conn
            return handler

        except Exception as e:
            raise NetworkError(f"Failed to get connection: {str(e)}")

    async def release_connection(self, handler: Union[XMLRPCHandler, JSONRPCHandler]):
        """
        Release a connection back to the pool.

        Args:
            handler: The connection handler to release
        """
        conn_id = str(id(handler))
        if conn_id in self._in_use:
            conn = self._in_use.pop(conn_id)
            if datetime.now() - conn['created_at'] <= self.max_lifetime:
                self._pool.append(conn)
            else:
                try:
                    await handler.close()
                except Exception as e:
                    logger.error(f"Error closing expired connection: {e}")

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
            handler = await self.get_connection()
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
        finally:
            if handler:
                await self.release_connection(handler)

    async def close(self):
        """Close all connections in the pool."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Close all connections in pool
        while self._pool:
            conn = self._pool.popleft()
            try:
                await conn['handler'].close()
            except Exception as e:
                logger.error(f"Error closing connection: {e}")

        # Close all in-use connections
        for conn in self._in_use.values():
            try:
                await conn['handler'].close()
            except Exception as e:
                logger.error(f"Error closing connection: {e}")
        self._in_use.clear() 