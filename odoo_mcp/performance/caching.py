import functools
import time
import logging
import asyncio  # Added missing import
from typing import Callable, Any, Optional, Union, Dict, List

logger = logging.getLogger(__name__)

# --- LRU Cache Implementation ---

# Option 1: Using functools.lru_cache (built-in)
# Pros: Simple, built-in. Suitable for caching pure functions.
# Cons: No built-in time-based expiration (TTL). Less flexible than cachetools.

def lru_cache_with_stats(maxsize=128, typed=False) -> Callable:
    """
    Create a decorator that wraps functools.lru_cache and adds basic logging.

    Logs cache hits/misses on each call to the decorated function.

    Args:
        maxsize: The maximum size of the LRU cache (passed to lru_cache).
        typed: Whether argument types should be considered for caching (passed to lru_cache).

    Returns:
        A decorator function.
    """
    def decorator(func: Callable) -> Callable:
        cached_func = functools.lru_cache(maxsize=maxsize, typed=typed)(func)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Note: Accessing cache_info() can affect performance slightly.
            # Consider adding conditional logging based on log level.
            # Also, cache_info() might not be perfectly thread-safe/async-safe
            # for stats if the underlying function is called concurrently,
            # but it's generally good for indicative stats.

            # Make args/kwargs hashable for cache lookup simulation (optional)
            # key = functools._make_key(args, kwargs, typed) # Internal API, use with caution

            # Call the cached function
            result = cached_func(*args, **kwargs)

            # Log cache status (example)
            info = cached_func.cache_info()
            logger.debug(f"Cache lookup for {func.__name__}: Hits={info.hits}, Misses={info.misses}, Size={info.currsize}/{info.maxsize}")

            return result

        # Expose cache_info and cache_clear from the underlying cached function
        wrapper.cache_info = cached_func.cache_info # type: ignore[attr-defined]
        wrapper.cache_clear = cached_func.cache_clear # type: ignore[attr-defined]
        return wrapper

    return decorator


# Option 2: Using cachetools (requires installation: pip install cachetools)
# Pros: More features like TTL (Time-To-Live) expiration, works well with async.
# Cons: External dependency.

# Example using cachetools.TTLCache (if cachetools is available)
try:
    from cachetools import TTLCache, cached, hashkey # Import hashkey directly

    class CacheManager:
        """
        Manages cache instances, primarily using cachetools if available.

        Provides decorators for applying TTL caching to functions and methods.
        """
        def __init__(self, default_maxsize: int = 128, default_ttl: int = 300):
            """
            Initialize the CacheManager.

            Args:
                default_maxsize: Default maximum size for created caches.
                default_ttl: Default time-to-live in seconds for created caches.
            """
            self.default_maxsize = default_maxsize
            self.default_ttl = default_ttl
            # Example cache instance for general Odoo read operations
            self.odoo_read_cache: TTLCache = TTLCache(maxsize=default_maxsize, ttl=default_ttl)
            # Add more specific caches as needed, e.g., for specific models or methods
            # self.partner_cache: TTLCache = TTLCache(maxsize=256, ttl=600)
            # Initialize with placeholders, configure() will set actual values
            self.odoo_read_cache: TTLCache = TTLCache(maxsize=1, ttl=1) # Placeholder
            logger.info(f"CacheManager initialized (defaults: maxsize={default_maxsize}, ttl={default_ttl}s). Waiting for configuration...")

        def configure(self, config: Dict[str, Any]):
            """
            Configure the cache manager settings from the loaded application config.

            Args:
                config: The main application configuration dictionary.
            """
            cache_config = config.get('cache', {}) # Look for a 'cache' section
            self.default_maxsize = cache_config.get('default_maxsize', 128)
            self.default_ttl = cache_config.get('default_ttl', 300)

            # Recreate the main cache instance with configured settings
            self.odoo_read_cache = TTLCache(maxsize=self.default_maxsize, ttl=self.default_ttl)

            logger.info(f"CacheManager configured: default_maxsize={self.default_maxsize}, default_ttl={self.default_ttl}s")
            logger.info(f"Recreated 'odoo_read_cache' with maxsize={self.odoo_read_cache.maxsize}, ttl={self.odoo_read_cache.ttl}s")
            # Configure other specific caches here if they exist

        def get_ttl_cache_decorator(self, cache_instance: Optional[TTLCache] = None, maxsize: Optional[int] = None, ttl: Optional[int] = None) -> Callable:
            """
            Get a decorator for applying TTL caching using cachetools.

            This decorator works for both synchronous and asynchronous functions.

            Args:
                cache_instance: An existing TTLCache instance to use. If None, a new
                                one is created based on maxsize/ttl.
                maxsize: Maximum size for the cache (if creating a new one).
                         Defaults to CacheManager's default_maxsize.
                ttl: Time-to-live in seconds for cache entries (if creating a new one).
                     Defaults to CacheManager's default_ttl.

            Returns:
                A decorator function that applies caching.
            """
            if cache_instance:
                 _cache = cache_instance
                 logger.debug(f"Using provided cache instance: {type(_cache).__name__} (maxsize={_cache.maxsize}, ttl={getattr(_cache, 'ttl', 'N/A')})")
            else:
                 _maxsize = maxsize if maxsize is not None else self.default_maxsize
                 _ttl = ttl if ttl is not None else self.default_ttl
                 _cache = TTLCache(maxsize=_maxsize, ttl=_ttl)
                 logger.debug(f"Created new TTLCache instance for decorator: maxsize={_maxsize}, ttl={_ttl}s")


            def decorator(func: Callable) -> Callable:
                """The actual decorator applying cachetools.cached."""
                # Ensure the function is awaitable if it needs to be
                is_async = asyncio.iscoroutinefunction(func)

                @cached(cache=_cache, key=hashkey)
                @functools.wraps(func)
                async def async_wrapper(*args, **kwargs):
                    logger.debug(f"Calling cached async function {func.__name__} with TTL cache.")
                    result = await func(*args, **kwargs)
                    info = _cache.currsize
                    logger.debug(f"Cache status for {func.__name__}: Size={info}/{_cache.maxsize}")
                    return result

                @cached(cache=_cache, key=hashkey)
                @functools.wraps(func)
                def sync_wrapper(*args, **kwargs):
                    logger.debug(f"Calling cached sync function {func.__name__} with TTL cache.")
                    result = func(*args, **kwargs)
                    # Use getattr for currsize as it might not be present on all cache types
                    size_info = getattr(_cache, 'currsize', 'N/A')
                    logger.debug(f"Cache status for {func.__name__}: Size={size_info}/{_cache.maxsize}")
                    return result

                return async_wrapper if is_async else sync_wrapper
            return decorator

    # Instantiate a global cache manager (or pass it around via dependency injection)
    # TODO: Read cache settings from config if available when CacheManager is instantiated globally
    # config = ... # Assume config is loaded somehow if running standalone
    # cache_manager = CacheManager(
    #     default_maxsize=config.get('cache', {}).get('default_maxsize', 128),
    #     default_ttl=config.get('cache', {}).get('default_ttl', 300)
    # )
    # Instantiate globally, but configuration will be applied later via configure()
    cache_manager = CacheManager()
    logger.info("cachetools library found. TTL caching enabled.")
    CACHE_TYPE: str = 'cachetools'

except ImportError:
    logger.warning("cachetools library not found. Falling back to functools.lru_cache (no TTL).")
    logger.warning("Install cachetools for TTL support: 'pip install cachetools' or 'pip install odoo-mcp-server[caching]'")
    cache_manager = None # No cache manager if library is missing
    CACHE_TYPE: str = 'functools'

    # Define a dummy decorator if cachetools is not available but TTL decorator is used
    class DummyCacheManager:
         """A dummy CacheManager used when cachetools is not installed."""
         def get_ttl_cache_decorator(self, cache_instance: Optional[Any] = None, maxsize: Optional[int] = None, ttl: Optional[int] = None) -> Callable:
              """Returns a decorator that does nothing or applies basic LRU."""
              logger.warning("cachetools not installed, TTL caching decorator has no effect.")
              def decorator(func: Callable) -> Callable:
                   """Dummy decorator returning the original function."""
                   # Option: Apply basic lru_cache as fallback?
                   # return lru_cache_with_stats(maxsize=maxsize or 128)(func)
                   return func # Current: No caching if TTL requested but unavailable
              return decorator
    cache_manager = DummyCacheManager()


# --- Example Usage ---

# Example function to cache using functools.lru_cache
@lru_cache_with_stats(maxsize=10)
def _example_lru_calc(a: int, b: int) -> int:
    """Example function demonstrating LRU cache."""
    logger.info(f"Performing expensive LRU calculation for {a}, {b}...")
    time.sleep(0.1) # Simulate work
    return a + b

# Example async function to cache using cachetools TTL cache
# Use the decorator provided by the cache_manager instance
if cache_manager and CACHE_TYPE == 'cachetools':
    # Use the default odoo_read_cache instance from the manager
    @cache_manager.get_ttl_cache_decorator(cache_instance=cache_manager.odoo_read_cache)
    async def _example_ttl_fetch(model: str, record_id: int) -> Dict:
        """Example async function demonstrating TTL cache."""
        logger.info(f"Fetching data via TTL cache for {model} ID {record_id} from Odoo...")
        # Simulate async network call
        await asyncio.sleep(0.2)
        return {"id": record_id, "name": f"{model}_{record_id}", "fetched_at": time.time()}
elif cache_manager: # Fallback if cachetools not installed but manager exists (Dummy)
     # Apply dummy decorator which does nothing or basic LRU
     @cache_manager.get_ttl_cache_decorator()
     async def _example_ttl_fetch(model: str, record_id: int) -> Dict:
        """Example async function (no TTL cache applied)."""
        logger.info(f"Fetching data for {model} ID {record_id} from Odoo (No TTL Cache)...")
        await asyncio.sleep(0.2)
        return {"id": record_id, "name": f"{model}_{record_id}", "fetched_at": time.time()}


async def _run_cache_tests():
    """Runs example tests for the caching mechanisms."""
    print("\n--- Testing functools.lru_cache ---")
    print(f"Result 1: {_example_lru_calc(1, 2)}")
    print(f"Result 2: {_example_lru_calc(1, 2)}") # Should be cached
    print(f"Result 3: {_example_lru_calc(2, 3)}")
    info = _example_lru_calc.cache_info() # type: ignore[attr-defined]
    print(f"Cache Info: Hits={info.hits}, Misses={info.misses}, Size={info.currsize}/{info.maxsize}")
    _example_lru_calc.cache_clear() # type: ignore[attr-defined]
    print("Cache cleared.")
    info = _example_lru_calc.cache_info() # type: ignore[attr-defined]
    print(f"Cache Info after clear: Hits={info.hits}, Misses={info.misses}, Size={info.currsize}/{info.maxsize}")

    # Check if the example TTL function exists before testing
    if '_example_ttl_fetch' in globals():
        print(f"\n--- Testing {CACHE_TYPE} Cache ---")
        fetch1 = await _example_ttl_fetch('res.partner', 1)
        print(f"Fetch 1: {fetch1}")
        fetch2 = await _example_ttl_fetch('res.partner', 1)
        print(f"Fetch 2: {fetch2}") # Should be cached
        fetch3 = await _example_ttl_fetch('res.users', 2)
        print(f"Fetch 3: {fetch3}")
        if CACHE_TYPE == 'cachetools':
            print("Waiting for cache to expire (default TTL)...")
            # Wait longer than the default TTL (e.g., 10s if default is low for testing)
            await asyncio.sleep(cache_manager.default_ttl + 1 if cache_manager else 11)
            fetch4 = await _example_ttl_fetch('res.partner', 1)
            print(f"Fetch 4 (after TTL): {fetch4}") # Should fetch again
        else:
             fetch4 = await _example_ttl_fetch('res.partner', 1)
             print(f"Fetch 4 (no TTL): {fetch4}") # Should likely be cached if LRU fallback used

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    # asyncio.run(_run_cache_tests()) # Uncomment to run example tests
    pass
