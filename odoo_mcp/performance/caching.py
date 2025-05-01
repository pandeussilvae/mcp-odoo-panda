import functools
import time
import logging
import asyncio
from typing import Callable, Any, Optional, Union, Dict, List
import sys

logger = logging.getLogger(__name__)

# Global variables
cache_manager = None
CACHE_TYPE = 'functools'

def make_key(*args, **kwargs):
    """Create a cache key from arguments."""
    # Convert args to a tuple of hashable items
    key_parts = []
    for arg in args:
        if isinstance(arg, (list, dict)):
            key_parts.append(str(arg))
        else:
            key_parts.append(arg)
    
    # Sort kwargs items to ensure consistent key generation
    sorted_kwargs = tuple(sorted((k, str(v) if isinstance(v, (list, dict)) else v) 
                               for k, v in kwargs.items()))
    
    return hash((tuple(key_parts), sorted_kwargs))

class DummyCacheManager:
    """A dummy CacheManager used when cachetools is not installed."""
    def __init__(self, default_maxsize: int = 128, default_ttl: int = 300):
        self.default_maxsize = default_maxsize
        self.default_ttl = default_ttl
        self.odoo_read_cache = None  # Initialize to None since we don't use it in dummy mode
        logger.info(f"DummyCacheManager initialized with defaults: maxsize={default_maxsize}, ttl={default_ttl}s")

    def configure(self, config: Dict[str, Any]):
        """Configure the dummy cache manager settings."""
        try:
            cache_config = config.get('cache', {})
            self.default_maxsize = cache_config.get('default_maxsize', self.default_maxsize)
            self.default_ttl = cache_config.get('default_ttl', self.default_ttl)
            logger.info(f"DummyCacheManager configured: maxsize={self.default_maxsize}, ttl={self.default_ttl}s")
        except Exception as e:
            logger.warning(f"Error configuring DummyCacheManager: {str(e)}")
            # Keep default values if configuration fails
            pass

    def get_ttl_cache_decorator(self, *args, **kwargs) -> Callable:
        """Get a decorator that applies basic LRU caching."""
        def decorator(func: Callable) -> Callable:
            @functools.lru_cache(maxsize=self.default_maxsize)
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)
            return wrapper
        return decorator

class CacheManager:
    """Manages cache instances using cachetools."""
    def __init__(self, default_maxsize: int = 128, default_ttl: int = 300):
        try:
            from cachetools import TTLCache, cached
            from cachetools.keys import hashkey
            self.default_maxsize = default_maxsize
            self.default_ttl = default_ttl
            self.TTLCache = TTLCache
            self.cached = cached
            self.hashkey = hashkey
            self.odoo_read_cache = TTLCache(maxsize=default_maxsize, ttl=default_ttl)
            logger.info(f"CacheManager initialized with defaults: maxsize={default_maxsize}, ttl={default_ttl}s")
        except ImportError as e:
            logger.error(f"Failed to initialize CacheManager: {str(e)}")
            raise

    def configure(self, config: Dict[str, Any]):
        """Configure the cache manager settings."""
        try:
            cache_config = config.get('cache', {})
            self.default_maxsize = cache_config.get('default_maxsize', self.default_maxsize)
            self.default_ttl = cache_config.get('default_ttl', self.default_ttl)
            self.odoo_read_cache = self.TTLCache(maxsize=self.default_maxsize, ttl=self.default_ttl)
            logger.info(f"CacheManager configured: maxsize={self.default_maxsize}, ttl={self.default_ttl}s")
        except Exception as e:
            logger.warning(f"Error configuring CacheManager: {str(e)}")
            # Keep default values if configuration fails
            pass

    def get_ttl_cache_decorator(self, cache_instance: Optional[Any] = None, maxsize: Optional[int] = None, ttl: Optional[int] = None) -> Callable:
        if cache_instance:
            _cache = cache_instance
        else:
            _maxsize = maxsize if maxsize is not None else self.default_maxsize
            _ttl = ttl if ttl is not None else self.default_ttl
            _cache = self.TTLCache(maxsize=_maxsize, ttl=_ttl)

        def decorator(func: Callable) -> Callable:
            is_async = asyncio.iscoroutinefunction(func)

            @self.cached(cache=_cache, key=self.hashkey)
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                result = await func(*args, **kwargs)
                return result

            @self.cached(cache=_cache, key=self.hashkey)
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return async_wrapper if is_async else sync_wrapper
        return decorator

def initialize_cache_manager(config: Optional[Dict[str, Any]] = None) -> bool:
    """Initialize the cache manager with proper error handling."""
    global cache_manager, CACHE_TYPE
    
    try:
        logger.info("Attempting to import cachetools...")
        logger.info(f"Python path: {sys.path}")
        from cachetools import TTLCache, cached
        from cachetools.keys import hashkey
        logger.info("Successfully imported cachetools")
        logger.info(f"cachetools version: {TTLCache.__module__}")

        # Create the cache manager instance
        cache_manager = CacheManager()
        CACHE_TYPE = 'cachetools'
        logger.info("CacheManager initialized successfully with cachetools")

        # Configure if config is provided
        if config:
            try:
                cache_manager.configure(config)
                logger.info("CacheManager configured successfully")
            except Exception as e:
                logger.warning(f"Failed to configure CacheManager: {str(e)}")
                # Continue with default values

        return True

    except Exception as e:
        logger.error(f"Failed to initialize cachetools: {str(e)}")
        logger.error(f"Python path: {sys.path}")
        logger.warning("Falling back to functools.lru_cache (no TTL).")
        
        # Create the dummy cache manager instance
        cache_manager = DummyCacheManager()
        CACHE_TYPE = 'functools'

        # Configure if config is provided
        if config:
            try:
                cache_manager.configure(config)
                logger.info("DummyCacheManager configured successfully")
            except Exception as e:
                logger.warning(f"Failed to configure DummyCacheManager: {str(e)}")
                # Continue with default values

        return False

# Initialize the cache manager if not already initialized
if cache_manager is None:
    initialize_cache_manager()

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
            # Call the cached function
            result = cached_func(*args, **kwargs)

            # Log cache status
            info = cached_func.cache_info()
            logger.debug(f"Cache lookup for {func.__name__}: Hits={info.hits}, Misses={info.misses}, Size={info.currsize}/{info.maxsize}")

            return result

        # Expose cache_info and cache_clear from the underlying cached function
        wrapper.cache_info = cached_func.cache_info # type: ignore[attr-defined]
        wrapper.cache_clear = cached_func.cache_clear # type: ignore[attr-defined]
        return wrapper

    return decorator

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
