"""
Cache Manager implementation for Odoo MCP Server.
This module provides caching functionality for Odoo API requests.
"""

import logging
import time
from typing import Dict, Any, Optional, Callable, TypeVar, cast
from functools import wraps
import cachetools

logger = logging.getLogger(__name__)

# Cache types
CACHE_TYPE = 'cachetools'  # Default cache type

class CacheManager:
    """Manages caching for Odoo API requests."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the cache manager.

        Args:
            config: Configuration dictionary containing cache settings
        """
        self.config = config
        self.cache_type = config.get('cache_type', CACHE_TYPE)
        self.default_ttl = config.get('cache_ttl', 300)  # 5 minutes default
        
        # Initialize caches
        self.odoo_read_cache = cachetools.TTLCache(
            maxsize=config.get('cache_max_size', 1000),
            ttl=self.default_ttl
        )
        
        self.odoo_search_cache = cachetools.TTLCache(
            maxsize=config.get('cache_max_size', 1000),
            ttl=self.default_ttl
        )
        
        self.odoo_fields_cache = cachetools.TTLCache(
            maxsize=config.get('cache_max_size', 100),
            ttl=self.default_ttl * 2  # Longer TTL for fields
        )

    def get_ttl_cache_decorator(self, cache_instance: Optional[cachetools.TTLCache] = None):
        """
        Get a TTL cache decorator for a function.

        Args:
            cache_instance: Optional specific cache instance to use

        Returns:
            Callable: Decorator function
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Generate cache key
                cache_key = self._generate_cache_key(func.__name__, args, kwargs)
                
                # Use specified cache or default to odoo_read_cache
                cache = cache_instance or self.odoo_read_cache
                
                # Check cache
                if cache_key in cache:
                    logger.debug(f"Cache hit for {func.__name__}")
                    return cache[cache_key]
                
                # Execute function
                result = await func(*args, **kwargs)
                
                # Cache result
                cache[cache_key] = result
                logger.debug(f"Cached result for {func.__name__}")
                
                return result
            return wrapper
        return decorator

    def _generate_cache_key(self, func_name: str, args: tuple, kwargs: dict) -> str:
        """
        Generate a cache key for a function call.

        Args:
            func_name: Name of the function
            args: Function arguments
            kwargs: Function keyword arguments

        Returns:
            str: Cache key
        """
        # Convert args and kwargs to a stable string representation
        key_parts = [func_name]
        
        # Add args
        for arg in args:
            if isinstance(arg, (str, int, float, bool)):
                key_parts.append(str(arg))
            elif isinstance(arg, (list, tuple)):
                key_parts.append(str(sorted(arg)))
            elif isinstance(arg, dict):
                key_parts.append(str(sorted(arg.items())))
            else:
                key_parts.append(str(arg))
        
        # Add kwargs
        for key, value in sorted(kwargs.items()):
            if isinstance(value, (str, int, float, bool)):
                key_parts.append(f"{key}:{value}")
            elif isinstance(value, (list, tuple)):
                key_parts.append(f"{key}:{sorted(value)}")
            elif isinstance(value, dict):
                key_parts.append(f"{key}:{sorted(value.items())}")
            else:
                key_parts.append(f"{key}:{value}")
        
        return "|".join(key_parts)

    def clear_cache(self, cache_name: Optional[str] = None):
        """
        Clear specified cache or all caches.

        Args:
            cache_name: Optional specific cache to clear
        """
        if cache_name == 'read':
            self.odoo_read_cache.clear()
        elif cache_name == 'search':
            self.odoo_search_cache.clear()
        elif cache_name == 'fields':
            self.odoo_fields_cache.clear()
        else:
            # Clear all caches
            self.odoo_read_cache.clear()
            self.odoo_search_cache.clear()
            self.odoo_fields_cache.clear()
        
        logger.info(f"Cleared cache: {cache_name if cache_name else 'all'}")

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get statistics for all caches.

        Returns:
            Dict[str, Any]: Cache statistics
        """
        return {
            'read_cache': {
                'size': len(self.odoo_read_cache),
                'maxsize': self.odoo_read_cache.maxsize,
                'ttl': self.odoo_read_cache.ttl
            },
            'search_cache': {
                'size': len(self.odoo_search_cache),
                'maxsize': self.odoo_search_cache.maxsize,
                'ttl': self.odoo_search_cache.ttl
            },
            'fields_cache': {
                'size': len(self.odoo_fields_cache),
                'maxsize': self.odoo_fields_cache.maxsize,
                'ttl': self.odoo_fields_cache.ttl
            }
        }

# Global cache manager instance
cache_manager: Optional[CacheManager] = None

def initialize_cache_manager(config: Dict[str, Any]) -> None:
    """
    Initialize the global cache manager.

    Args:
        config: Configuration dictionary
    """
    global cache_manager
    cache_manager = CacheManager(config)
    logger.info("Cache manager initialized")
