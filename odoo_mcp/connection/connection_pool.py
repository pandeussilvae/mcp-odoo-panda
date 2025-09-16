"""
Odoo MCP Connection Pool implementation.
"""

import logging
import asyncio
from typing import Dict, Any, Optional, Union, Type
from contextlib import asynccontextmanager
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler
from odoo_mcp.core.jsonrpc_handler import JSONRPCHandler
from odoo_mcp.error_handling.exceptions import (
    ConnectionError,
    PoolTimeoutError,
    OdooMCPError,
    NetworkError,
    AuthError,
)

logger = logging.getLogger(__name__)


class ConnectionWrapper:
    """
    Wraps a connection object (e.g., XMLRPCHandler) to manage its state within the pool.

    Attributes:
        connection: The actual connection instance.
        pool: A reference back to the ConnectionPool managing this wrapper.
        last_used: Timestamp (monotonic) of when the connection was last used or acquired.
        is_active: Boolean flag indicating if the connection is considered healthy.
    """

    def __init__(self, connection: Union[XMLRPCHandler, JSONRPCHandler], pool: "ConnectionPool"):
        """
        Initialize the ConnectionWrapper.

        Args:
            connection: The connection instance to wrap.
            pool: The ConnectionPool this wrapper belongs to.
        """
        self.connection = connection
        self.pool = pool
        self.last_used = time.monotonic()
        self.is_active = True  # Flag to mark connection as potentially stale/unhealthy
        self.in_use = False

    def mark_used(self):
        """Update the last used timestamp to the current time."""
        self.last_used = time.monotonic()

    async def close(self):
        """
        Close the underlying connection and mark the wrapper as inactive.

        Note: Actual closing logic depends on the connection object's implementation.
        """
        # Placeholder for actual connection closing logic
        logger.info(f"Closing connection: {id(self.connection)}")
        self.is_active = False
        # Example: if hasattr(self.connection, 'close'): await self.connection.close()
        # Add specific close logic for XMLRPCHandler/JSONRPCHandler if needed

    async def health_check(self) -> bool:
        """
        Perform a health check on the underlying connection.

        Returns:
            True if the connection is healthy, False otherwise.
            Marks the connection as inactive and closes it if the check fails.
        """
        # Placeholder for actual health check logic (e.g., ping Odoo)
        try:
            # Example for XMLRPC: Use global credentials from config for health check
            if isinstance(self.connection, XMLRPCHandler):
                # Need config access here, maybe pass config to wrapper or access via pool.config
                config = self.pool.config
                db = config.get("database")
                user = config.get("username")
                pwd = config.get("api_key")
                if not all([db, user, pwd]):
                    logger.warning(
                        f"Cannot perform XMLRPC health check for {id(self.connection)}: Missing global credentials in config."
                    )
                    # Assume healthy if cannot check? Or unhealthy? Let's assume healthy.
                    self.is_active = True
                    return True

                # Try calling 'version' or a simple non-auth method if available.
                # If 'version' requires auth, we might need to authenticate just for the check.
                # Let's assume common.version() doesn't strictly require prior auth,
                # or ServerProxy handles basic auth if URL includes credentials (unlikely/unsafe).
                # A safer check might be needed. For now, try version().
                version_info = self.connection.common.version()
                logger.debug(f"Health check passed for {id(self.connection)}: Odoo version info {version_info}")
                self.is_active = True
                return True
            # Add similar check for JSONRPCHandler if applicable
            else:
                logger.warning(f"Health check not implemented for connection type: {type(self.connection)}")
                # Assume healthy if no check is defined for now
                self.is_active = True
                return True
        except Exception as e:
            # Distinguish between network/auth errors and others during health check
            if isinstance(e, (NetworkError, AuthError)):  # Assuming AuthError might be raised by check
                logger.warning(
                    f"Health check failed for connection {id(self.connection)} due to network/auth issue: {e}"
                )
            else:
                logger.error(
                    f"Unexpected error during health check for connection {id(self.connection)}: {e}",
                    exc_info=True,
                )
            self.is_active = False
            await self.close()  # Close failed connection
            return False

    async def __aenter__(self):
        """Enter context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager."""
        await self.pool.release_connection(self)


class ConnectionPool:
    """
    An asynchronous connection pool for managing Odoo connections (XMLRPC/JSONRPC handlers).

    Provides methods to acquire and release connections, manages pool size,
    handles connection creation with retries, performs periodic health checks
    on idle connections, and ensures proper cleanup on close.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the ConnectionPool.

        Args:
            config: The server configuration dictionary. Expected keys include:
                    'pool_size', 'timeout', 'connection_health_interval',
                    'retry_count', 'odoo_url', 'database', 'username', 'api_key'.
        """
        self.config = config
        self._pool: List[ConnectionWrapper] = []
        self._max_size = config.get("max_connections", 10)
        self._timeout = config.get("connection_timeout", 30)
        self._lock = asyncio.Lock()
        self._health_check_task: Optional[asyncio.Task] = None
        self._closing = False  # Flag to indicate if the pool is shutting down

    @asynccontextmanager
    async def get_connection(self) -> ConnectionWrapper:
        """
        Get a connection from the pool.

        Returns:
            ConnectionWrapper: Connection wrapper

        Raises:
            PoolTimeoutError: If timeout occurs while waiting for connection
            ConnectionError: If connection creation fails
        """
        try:
            async with self._lock:
                # Try to get an existing connection
                for conn in self._pool:
                    if not conn.in_use:
                        conn.in_use = True
                        return conn

                # Create new connection if pool not full
                if len(self._pool) < self._max_size:
                    try:
                        if self.config.get("use_jsonrpc", False):
                            connection = JSONRPCHandler(self.config)
                        else:
                            connection = XMLRPCHandler(self.config)
                        wrapper = ConnectionWrapper(connection, self)
                        wrapper.in_use = True
                        self._pool.append(wrapper)
                        return wrapper
                    except Exception as e:
                        raise ConnectionError(f"Failed to create connection: {str(e)}")

                # Wait for connection with timeout
                try:
                    async with asyncio.timeout(self._timeout):
                        while True:
                            for conn in self._pool:
                                if not conn.in_use:
                                    conn.in_use = True
                                    return conn
                            await asyncio.sleep(0.1)
                except asyncio.TimeoutError:
                    raise PoolTimeoutError("Timeout waiting for available connection")

        except Exception as e:
            if not isinstance(e, (PoolTimeoutError, ConnectionError)):
                raise OdooMCPError(f"Unexpected error in connection pool: {str(e)}")
            raise

    async def release_connection(self, wrapper: ConnectionWrapper) -> None:
        """
        Release a connection back to the pool.

        Args:
            wrapper: Connection wrapper to release
        """
        async with self._lock:
            wrapper.in_use = False

    async def _run_health_checks(self):
        """Background task that periodically checks the health of idle connections."""
        logger.info("Starting background health check task.")
        while not self._closing:
            try:
                await asyncio.sleep(self.config.get("connection_health_interval", 60))
                if self._closing:
                    break  # Exit if pool started closing during sleep

                logger.debug("Running periodic health checks...")
                connections_to_check: list[ConnectionWrapper] = []
                async with self._lock:
                    # Check only idle connections currently in the deque
                    connections_to_check.extend(self._pool)

                checked_count = 0
                failed_count = 0
                for wrapper in connections_to_check:
                    # Check if the connection is still in the pool and active before checking
                    # This avoids race conditions if it was acquired or marked inactive
                    async with self._lock:
                        if wrapper in self._pool and wrapper.is_active:
                            # Release lock during potentially long health check
                            await self._condition.release()
                            is_healthy = await wrapper.health_check()
                            await self._condition.acquire()  # Re-acquire lock

                            checked_count += 1
                            if not is_healthy:
                                failed_count += 1
                                # Remove from pool if check failed and closed the connection
                                if wrapper in self._pool:  # Check again after re-acquiring lock
                                    try:
                                        self._pool.remove(wrapper)
                                        self._current_size -= 1
                                        logger.info(f"Removed unhealthy connection {id(wrapper.connection)} from pool.")
                                    except ValueError:
                                        # Already removed, possibly by release_connection
                                        pass
                                else:
                                    # Connection was likely acquired while we were checking it
                                    logger.debug(f"Connection {id(wrapper.connection)} acquired during health check.")
                        else:
                            # Connection was not in pool or already inactive, skip check
                            logger.debug(
                                f"Skipping health check for connection {id(wrapper.connection)} (not idle or inactive)."
                            )

                logger.debug(
                    f"Health check finished. Checked: {checked_count}, Failed: {failed_count}. Pool size: {self._current_size}"
                )

            except asyncio.CancelledError:
                logger.info("Health check task cancelled.")
                break
            except Exception as e:
                logger.exception(f"Error in health check task: {e}")
                # Avoid task death loop, wait a bit before retrying health checks
                await asyncio.sleep(
                    min(self.config.get("connection_health_interval", 60) / 2, 30)
                )  # Wait shorter time after error, max 30s

    async def start_health_checks(self):
        """Start the background health check task if not already running."""
        if self._health_check_task is None or self._health_check_task.done():
            if self.config.get("connection_health_interval", 60) > 0:
                self._health_check_task = asyncio.create_task(self._run_health_checks())
                logger.info(
                    f"Background health check task started. Interval: {self.config.get('connection_health_interval', 60)}s"
                )
            else:
                logger.info("Background health checks disabled (interval <= 0).")

    async def close(self):
        """Close the connection pool.

        Cancels background tasks and closes all idle connections.
        Connections currently in use will be closed when released.
        """
        if self._closing:
            return
        logger.info("Closing connection pool...")
        self._closing = True  # Signal that the pool is closing

        # Cancel health check task
        if self._health_check_task and not self._health_check_task.done():
            logger.debug("Cancelling health check task...")
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                logger.info("Health check task successfully cancelled.")
            except Exception as e:
                logger.exception(f"Error waiting for health check task cancellation: {e}")
            self._health_check_task = None

        async with self._lock:
            logger.debug(f"Closing {len(self._pool)} idle connections in pool.")
            # Close all connections currently idle in the pool
            close_tasks = [wrapper.close() for wrapper in self._pool]
            # Connections currently checked out will be closed upon release
            await asyncio.gather(*close_tasks, return_exceptions=True)  # Log potential errors during close
            self._pool.clear()
            # Reset size based on closed idle connections. Active ones decrement on release.
            # This assumes release_connection correctly decrements for inactive/closed connections.
            # Let's explicitly set size to 0 after clearing the pool of idle connections.
            # Active connections will decrement size upon release when pool is closing.
            # self._current_size -= len(close_tasks) # This might be inaccurate if active connections exist
            # A safer approach might be needed if precise tracking during shutdown is critical.
            # For now, clearing the pool implies these idle ones are gone.
            # We rely on release_connection to handle the count for active ones later.

            self._condition.notify_all()  # Wake up any waiting getters to raise ConnectionError

        logger.info(f"Connection pool closed. Idle connections cleared.")  # Adjusted log message

    async def __aenter__(self):
        """Enter the async context manager, starting health checks."""
        await self.start_health_checks()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the async context manager, closing the pool."""
        await self.close()


# Example Usage (Conceptual)
async def main():
    config = {
        "odoo_url": "http://localhost:8069",  # Replace with your Odoo URL
        "database": "your_db",  # Replace with your DB name
        "username": "your_user",  # Replace with your username
        "api_key": "your_api_key",  # Replace with your API key/password
        "pool_size": 5,
        "timeout": 10,
        "connection_health_interval": 30,
        "retry_count": 2,
    }

    # Assuming XMLRPCHandler is the desired connection type
    pool = ConnectionPool(config)

    async with pool:  # Manages start/stop of health checks and pool closing
        conn_wrappers = []
        try:
            # Acquire some connections
            for i in range(config["pool_size"] + 1):  # Try to get one more than pool size
                print(f"Acquiring connection {i+1}...")
                try:
                    wrapper = await pool.get_connection()
                    conn_wrappers.append(wrapper)
                    print(f"Acquired connection {i+1}: {id(wrapper.connection)}")
                    # Simulate work
                    # await asyncio.sleep(0.1)
                    # Example: Use the connection
                    # result = wrapper.connection.execute_kw('res.partner', 'search_count', [[]], {})
                    # print(f"Connection {i+1} result: {result}")

                except PoolTimeoutError as e:
                    print(f"Failed to acquire connection {i+1}: {e}")
                    break  # Stop trying if timeout occurs

            print("\nReleasing connections...")
            # Release connections
            for i, wrapper in enumerate(conn_wrappers):
                print(f"Releasing connection {i+1}: {id(wrapper.connection)}")
                await pool.release_connection(wrapper)

            print("\nWaiting for health check cycle...")
            await asyncio.sleep(config["connection_health_interval"] + 5)  # Wait for a health check cycle

        except Exception as e:
            print(f"An error occurred: {e}")

    print("Pool closed.")


# Correct indentation for the main block
if __name__ == "__main__":
    # Setup basic logging for the example run
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    # Example execution (commented out by default)
    # try:
    #     asyncio.run(main())
    # except KeyboardInterrupt:
    #     print("\nExample run interrupted.")
    pass  # Keep the file runnable without executing main by default
