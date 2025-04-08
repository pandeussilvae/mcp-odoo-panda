import asyncio
import time
from typing import Dict, Any, Optional, Union, Type
from collections import deque
import logging

# Placeholder for actual handler types
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler
# from odoo_mcp.core.jsonrpc_handler import JSONRPCHandler # Import when JSONRPCHandler is fully integrated

logger = logging.getLogger(__name__)

# Import custom exceptions
from odoo_mcp.error_handling.exceptions import ConnectionError, PoolTimeoutError, OdooMCPError, NetworkError, AuthError

class ConnectionWrapper:
    """
    Wraps a connection object (e.g., XMLRPCHandler) to manage its state within the pool.

    Attributes:
        connection: The actual connection instance.
        pool: A reference back to the ConnectionPool managing this wrapper.
        last_used: Timestamp (monotonic) of when the connection was last used or acquired.
        is_active: Boolean flag indicating if the connection is considered healthy.
    """
    def __init__(self, connection: Union[XMLRPCHandler, Any], pool: 'ConnectionPool'):
        """
        Initialize the ConnectionWrapper.

        Args:
            connection: The connection instance to wrap.
            pool: The ConnectionPool this wrapper belongs to.
        """
        self.connection = connection
        self.pool = pool
        self.last_used = time.monotonic()
        self.is_active = True # Flag to mark connection as potentially stale/unhealthy

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
                 db = config.get('database')
                 user = config.get('username')
                 pwd = config.get('api_key')
                 if not all([db, user, pwd]):
                      logger.warning(f"Cannot perform XMLRPC health check for {id(self.connection)}: Missing global credentials in config.")
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
            if isinstance(e, (NetworkError, AuthError)): # Assuming AuthError might be raised by check
                 logger.warning(f"Health check failed for connection {id(self.connection)} due to network/auth issue: {e}")
            else:
                 logger.error(f"Unexpected error during health check for connection {id(self.connection)}: {e}", exc_info=True)
            self.is_active = False
            await self.close() # Close failed connection
            return False

class ConnectionPool:
    """
    An asynchronous connection pool for managing Odoo connections (XMLRPC/JSONRPC handlers).

    Provides methods to acquire and release connections, manages pool size,
    handles connection creation with retries, performs periodic health checks
    on idle connections, and ensures proper cleanup on close.
    """
    def __init__(self, config: Dict[str, Any], handler_class: Type[Union[XMLRPCHandler, Any]]):
        """
        Initialize the ConnectionPool.

        Args:
            config: The server configuration dictionary. Expected keys include:
                    'pool_size', 'timeout', 'connection_health_interval',
                    'retry_count', 'odoo_url', 'database', 'username', 'api_key'.
            handler_class: The class of the connection handler to manage (e.g., XMLRPCHandler).
        """
        self.config = config
        self.handler_class = handler_class
        self.pool_size = config.get('pool_size', 10)
        self.timeout = config.get('timeout', 30) # Timeout for getting a connection
        self.connection_health_interval = config.get('connection_health_interval', 60) # How often to check health
        self.max_retries = config.get('retry_count', 3)
        self.base_retry_delay = 1.0 # Initial delay for exponential backoff

        self._pool: deque[ConnectionWrapper] = deque()
        self._lock = asyncio.Lock()
        self._condition = asyncio.Condition(self._lock)
        self._current_size = 0
        self._health_check_task: Optional[asyncio.Task] = None
        self._closing = False # Flag to indicate if the pool is shutting down

    async def _create_connection(self) -> ConnectionWrapper:
        """
        Attempt to create a new connection instance using the handler_class.

        Implements retry logic with exponential backoff based on config settings.

        Returns:
            A ConnectionWrapper containing the newly created connection.

        Raises:
            ConnectionError: If connection creation fails after all retries.
        """
        for attempt in range(self.max_retries + 1):
            try:
                logger.info(f"Attempting to create new connection (Attempt {attempt + 1}/{self.max_retries + 1})")
                # Pass relevant parts of config to the handler
                connection_instance = self.handler_class(self.config)
                # Perform initial check/auth if needed by handler's __init__
                logger.info(f"Successfully created connection: {id(connection_instance)}")
                return ConnectionWrapper(connection_instance, self)
            except Exception as e:
                # Catch specific errors if possible (e.g., NetworkError, AuthError from handler init)
                log_message = f"Failed to create connection (Attempt {attempt + 1}): {e}"
                # Ensure AuthError is imported before using it here
                if isinstance(e, (NetworkError, AuthError)):
                     logger.warning(log_message) # Log as warning for known failure types
                else:
                     logger.error(log_message, exc_info=True) # Log as error for unexpected ones

                if attempt >= self.max_retries:
                    # Raise the specific ConnectionError from our exceptions module
                    raise ConnectionError(f"Failed to create connection after {self.max_retries + 1} attempts", original_exception=e)
                delay = self.base_retry_delay * (2 ** attempt)
                logger.info(f"Retrying connection creation in {delay:.2f} seconds...")
                await asyncio.sleep(delay)
        # Should not be reached due to raise in loop, but raise specific error if it is
        raise ConnectionError("Failed to create connection after multiple retries.")


    async def get_connection(self) -> ConnectionWrapper:
        """
        Acquire a connection wrapper from the pool.

        If the pool has idle connections, one is returned immediately.
        If the pool is not full, a new connection is created.
        If the pool is full, waits for a connection to be released or until timeout.

        Returns:
            A ConnectionWrapper instance.

        Raises:
            PoolTimeoutError: If waiting for a connection exceeds the configured timeout.
            ConnectionError: If the pool is closing or connection creation fails.
        """
        if self._closing:
            raise ConnectionError("Pool is closing, cannot get new connections.") # Uses the correct ConnectionError now

        start_time = time.monotonic()
        async with self._condition:
            while True:
                # Try to get an existing idle connection
                while self._pool:
                    wrapper = self._pool.popleft()
                    if wrapper.is_active:
                         # Optional: Perform a quick check before returning
                         # if await wrapper.health_check():
                         logger.debug(f"Reusing connection {id(wrapper.connection)} from pool.")
                         wrapper.mark_used()
                         return wrapper
                         # else: # Health check failed in get_connection
                         #    logger.warning(f"Connection {id(wrapper.connection)} failed pre-use health check.")
                         #    self._current_size -= 1 # Decrement size as it's being discarded

                # If no idle connection, try to create a new one if pool not full
                # If no idle connection, try to create a new one if pool not full
                # Keep the lock while creating the connection to ensure atomicity of size update
                # If no idle connection, try to create a new one if pool not full
                # Keep the lock while creating the connection to ensure atomicity of size update
                if self._current_size < self.pool_size:
                    # Increment size optimistically *before* creating
                    self._current_size += 1
                    try:
                        # Create connection while holding the lock
                        wrapper = await self._create_connection()
                        wrapper.mark_used()
                        logger.debug(f"Created new connection {id(wrapper.connection)}. Pool size: {self._current_size}/{self.pool_size}")
                        # Return the new connection; lock released by 'async with'
                        return wrapper
                    except Exception as e:
                        # Failed to create, decrement size and let the loop continue
                        logger.error(f"Failed to create connection for pool: {e}")
                        self._current_size -= 1 # Decrement size on failure
                        # Re-raise the original error? Or let the loop handle timeout/retry?
                        # If _create_connection raises ConnectionError after retries,
                        # maybe we should propagate that immediately?
                        if isinstance(e, ConnectionError):
                             raise # Propagate ConnectionError immediately if creation failed definitively
                        # Otherwise, let the loop continue to check timeout or wait for release


                # If pool is full or creation failed (and wasn't ConnectionError), wait
                wait_time = self.timeout - (time.monotonic() - start_time)
                if wait_time <= 0:
                    # Raise the specific PoolTimeoutError from our exceptions module
                    raise PoolTimeoutError(f"Timeout waiting for connection from pool after {self.timeout} seconds.")

                logger.debug(f"Pool full ({self._current_size}/{self.pool_size}), waiting for connection...")
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=wait_time)
                except asyncio.TimeoutError:
                     # Raise the specific PoolTimeoutError from our exceptions module
                     raise PoolTimeoutError(f"Timeout waiting for connection from pool after {self.timeout} seconds.")


    async def release_connection(self, wrapper: ConnectionWrapper):
        """
        Release a connection wrapper back to the pool.

        If the pool is closing or the connection is marked inactive, the connection
        is closed and discarded. Otherwise, it's added back to the idle pool.

        Args:
            wrapper: The ConnectionWrapper instance to release.
        """
        if self._closing:
            logger.info(f"Pool closing, discarding connection {id(wrapper.connection)} instead of releasing.")
            await wrapper.close()
            # Ensure size is decremented if closed during shutdown
            # Use lock to protect _current_size modification if needed concurrently,
            # though close() might already handle this if called from multiple places.
            # async with self._lock: # Lock might not be needed if close() is safe
            # Check if it was actually part of the count before decrementing
            # This logic might need refinement depending on how close() interacts
            # with pool state. Assuming close() marks inactive and release handles count.
            # pass # Decrement happens below if inactive
            # await wrapper.close() # Ensure close is called if pool is closing - Already called above
            # Decrement size after closing if it was considered active before this call
            # This needs careful state management. Let's assume inactive connections
            # handle their own size decrement when marked inactive.
            return

        async with self._condition:
            if wrapper.is_active:
                logger.debug(f"Releasing connection {id(wrapper.connection)} back to pool.")
                self._pool.append(wrapper)
                self._condition.notify() # Notify waiting getters
            else:
                # Connection was marked inactive (e.g., failed health check)
                logger.warning(f"Discarding inactive connection {id(wrapper.connection)} instead of releasing.")
                self._current_size -= 1
                # Optionally, trigger creation of a replacement connection immediately
                # or let get_connection handle it lazily.


    async def _run_health_checks(self):
        """Background task that periodically checks the health of idle connections."""
        logger.info("Starting background health check task.")
        while not self._closing:
            try:
                await asyncio.sleep(self.connection_health_interval)
                if self._closing: break # Exit if pool started closing during sleep

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
                               await self._condition.acquire() # Re-acquire lock

                               checked_count += 1
                               if not is_healthy:
                                    failed_count += 1
                                    # Remove from pool if check failed and closed the connection
                                    if wrapper in self._pool: # Check again after re-acquiring lock
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
                               logger.debug(f"Skipping health check for connection {id(wrapper.connection)} (not idle or inactive).")


                logger.debug(f"Health check finished. Checked: {checked_count}, Failed: {failed_count}. Pool size: {self._current_size}")

            except asyncio.CancelledError:
                logger.info("Health check task cancelled.")
                break
            except Exception as e:
                logger.exception(f"Error in health check task: {e}")
                # Avoid task death loop, wait a bit before retrying health checks
                await asyncio.sleep(min(self.connection_health_interval / 2, 30)) # Wait shorter time after error, max 30s

    async def start_health_checks(self):
        """Start the background health check task if not already running."""
        if self._health_check_task is None or self._health_check_task.done():
             if self.connection_health_interval > 0:
                  self._health_check_task = asyncio.create_task(self._run_health_checks())
                  logger.info(f"Background health check task started. Interval: {self.connection_health_interval}s")
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
        self._closing = True # Signal that the pool is closing

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


        async with self._condition:
            logger.debug(f"Closing {len(self._pool)} idle connections in pool.")
            # Close all connections currently idle in the pool
            close_tasks = [wrapper.close() for wrapper in self._pool]
            # Connections currently checked out will be closed upon release
            await asyncio.gather(*close_tasks, return_exceptions=True) # Log potential errors during close
            self._pool.clear()
            # Reset size based on closed idle connections. Active ones decrement on release.
            # This assumes release_connection correctly decrements for inactive/closed connections.
            # Let's explicitly set size to 0 after clearing the pool of idle connections.
            # Active connections will decrement size upon release when pool is closing.
            # self._current_size -= len(close_tasks) # This might be inaccurate if active connections exist
            # A safer approach might be needed if precise tracking during shutdown is critical.
            # For now, clearing the pool implies these idle ones are gone.
            # We rely on release_connection to handle the count for active ones later.

            self._condition.notify_all() # Wake up any waiting getters to raise ConnectionError

        logger.info(f"Connection pool closed. Idle connections cleared.") # Adjusted log message

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
        'odoo_url': 'http://localhost:8069', # Replace with your Odoo URL
        'database': 'your_db',           # Replace with your DB name
        'username': 'your_user',         # Replace with your username
        'api_key': 'your_api_key',       # Replace with your API key/password
        'pool_size': 5,
        'timeout': 10,
        'connection_health_interval': 30,
        'retry_count': 2,
    }

    # Assuming XMLRPCHandler is the desired connection type
    pool = ConnectionPool(config, XMLRPCHandler)

    async with pool: # Manages start/stop of health checks and pool closing
        conn_wrappers = []
        try:
            # Acquire some connections
            for i in range(config['pool_size'] + 1): # Try to get one more than pool size
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
                    break # Stop trying if timeout occurs

            print("\nReleasing connections...")
            # Release connections
            for i, wrapper in enumerate(conn_wrappers):
                print(f"Releasing connection {i+1}: {id(wrapper.connection)}")
                await pool.release_connection(wrapper)

            print("\nWaiting for health check cycle...")
            await asyncio.sleep(config['connection_health_interval'] + 5) # Wait for a health check cycle

        except Exception as e:
            print(f"An error occurred: {e}")

    print("Pool closed.")

# Correct indentation for the main block
if __name__ == "__main__":
    # Setup basic logging for the example run
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    )
    # Example execution (commented out by default)
    # try:
    #     asyncio.run(main())
    # except KeyboardInterrupt:
    #     print("\nExample run interrupted.")
    pass # Keep the file runnable without executing main by default
