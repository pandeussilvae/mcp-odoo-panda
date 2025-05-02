"""
Cache management for Odoo MCP Server.
This module provides caching functionality for Odoo requests.
"""

import logging
import time
import functools
from typing import Dict, Any, Optional, Callable, TypeVar, cast
from enum import Enum

from odoo_mcp.error_handling.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

class CACHE_TYPE(str, Enum):
    """Cache types supported by the server."""
    CACHETOOLS = 'cachetools'
    MEMORY = 'memory'
    REDIS = 'redis'

# Global cache manager instance
_cache_manager = None

def initialize_cache_manager(config: Dict[str, Any]) -> None:
    """
    Initialize the global cache manager.

    Args:
        config: Configuration dictionary

    Raises:
        ConfigurationError: If the cache manager is already initialized
    """
    global _cache_manager
    if _cache_manager is not None:
        raise ConfigurationError("Cache manager is already initialized")
    
    _cache_manager = CacheManager(config)
    logger.info("Cache manager initialized successfully")

def get_cache_manager() -> 'CacheManager':
    """
    Get the global cache manager instance.

    Returns:
        CacheManager: The global cache manager instance

    Raises:
        ConfigurationError: If the cache manager is not initialized
    """
    if _cache_manager is None:
        raise ConfigurationError("Cache manager is not initialized")
    return _cache_manager

class CacheManager:
    """Cache manager implementation."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize cache manager.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.cache_type = config.get('cache_type', CACHE_TYPE.MEMORY)
        self.ttl = config.get('cache_ttl', 300)  # Default 5 minutes
        self.max_size = config.get('cache_max_size', 1000)
        
        # Initialize caches
        self._init_caches()
        
        logger.info(f"Cache manager initialized with type: {self.cache_type}")

    def _init_caches(self) -> None:
        """Initialize cache instances based on cache type."""
        if self.cache_type == CACHE_TYPE.CACHETOOLS:
            try:
                from cachetools import TTLCache
                self.odoo_read_cache = TTLCache(maxsize=self.max_size, ttl=self.ttl)
                self.odoo_write_cache = TTLCache(maxsize=self.max_size, ttl=self.ttl)
                self.method_cache = TTLCache(maxsize=self.max_size, ttl=self.ttl)
            except ImportError:
                logger.warning("cachetools not found, falling back to memory cache")
                self.cache_type = CACHE_TYPE.MEMORY
                self._init_memory_cache()
        elif self.cache_type == CACHE_TYPE.REDIS:
            try:
                import redis
                self.redis_client = redis.Redis(
                    host=self.config.get('redis_host', 'localhost'),
                    port=self.config.get('redis_port', 6379),
                    db=self.config.get('redis_db', 0)
                )
            except ImportError:
                logger.warning("redis not found, falling back to memory cache")
                self.cache_type = CACHE_TYPE.MEMORY
                self._init_memory_cache()
        else:
            self._init_memory_cache()

    def _init_memory_cache(self) -> None:
        """Initialize in-memory caches."""
        self.odoo_read_cache = {}
        self.odoo_write_cache = {}
        self.method_cache = {}

    def get_ttl_cache_decorator(self, cache_instance: Optional[Dict] = None) -> Callable:
        """
        Get a TTL cache decorator.

        Args:
            cache_instance: Cache instance to use

        Returns:
            Callable: Cache decorator
        """
        if cache_instance is None:
            cache_instance = self.method_cache

        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                # Generate cache key
                key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
                
                # Check cache
                if key in cache_instance:
                    logger.debug(f"Cache hit for {func.__name__}")
                    return cache_instance[key]
                
                # Execute function
                result = await func(*args, **kwargs)
                
                # Cache result
                cache_instance[key] = result
                logger.debug(f"Cached result for {func.__name__}")
                
                return result
            return wrapper
        return decorator

    def clear_cache(self, cache_type: Optional[str] = None) -> None:
        """
        Clear cache.

        Args:
            cache_type: Type of cache to clear (None for all)
        """
        if cache_type == 'read' or cache_type is None:
            self.odoo_read_cache.clear()
        if cache_type == 'write' or cache_type is None:
            self.odoo_write_cache.clear()
        if cache_type == 'method' or cache_type is None:
            self.method_cache.clear()
        
        logger.info(f"Cache cleared for type: {cache_type or 'all'}")

    async def close(self) -> None:
        """Clean up resources."""
        self.clear_cache()
        if hasattr(self, 'redis_client'):
            await self.redis_client.close()
