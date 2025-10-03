"""
Base Handler for Odoo Communication Protocols.
This module provides a unified base class for XMLRPC and JSONRPC handlers.
"""

import asyncio
import logging
import ssl
from abc import ABC, abstractmethod
from functools import wraps
from typing import Any, Dict, List, Optional, Union

from odoo_mcp.error_handling.exceptions import (
    AuthError,
    ConfigurationError,
    NetworkError,
    OdooMCPError,
)
from odoo_mcp.performance.caching import CACHE_TYPE, get_cache_manager, initialize_cache_manager

logger = logging.getLogger(__name__)


def safe_cache_decorator(func):
    """Safe wrapper for cache decorator that handles None cache_manager."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            cache_manager = get_cache_manager()
            if cache_manager and CACHE_TYPE == "cachetools":
                cache_decorator = cache_manager.get_ttl_cache_decorator(
                    cache_instance=cache_manager.odoo_read_cache
                )
                return await cache_decorator(func)(*args, **kwargs)
        except ConfigurationError:
            logger.warning("Cache manager not initialized, executing without cache")
        return await func(*args, **kwargs)
    return wrapper


class BaseOdooHandler(ABC):
    """
    Base class for Odoo communication handlers.
    
    Provides common functionality for both XMLRPC and JSONRPC handlers including:
    - SSL/TLS configuration
    - Authentication management
    - Caching support
    - Error handling
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the base handler.
        
        Args:
            config: Configuration dictionary containing connection parameters
        """
        self.config = config
        self.odoo_url = config.get("odoo_url")
        self.database = config.get("database")
        self.username = config.get("username")
        self.password = config.get("api_key")
        
        # Global authentication credentials
        self.global_uid = None
        self.global_password = None
        
        # Initialize cache manager
        self._initialize_cache()
        
        # Configure SSL/TLS
        self.ssl_context = self._configure_ssl()
        
        # Validate configuration
        self._validate_config()
        
        logger.info(f"Initialized {self.__class__.__name__} with URL: {self.odoo_url}")

    def _initialize_cache(self) -> None:
        """Initialize cache manager if not already initialized."""
        try:
            get_cache_manager()
        except ConfigurationError:
            initialize_cache_manager(self.config)

    def _configure_ssl(self) -> Optional[ssl.SSLContext]:
        """Configure SSL/TLS context for secure connections."""
        if not self.odoo_url or not self.odoo_url.startswith("https://"):
            return None
            
        try:
            tls_version_str = self.config.get("tls_version", "TLSv1.3").upper().replace(".", "_")
            protocol_version = ssl.PROTOCOL_TLS_CLIENT
            ssl_context = ssl.SSLContext(protocol_version)
            ssl_context.check_hostname = True
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            ssl_context.load_default_certs()

            # Set minimum TLS version
            if hasattr(ssl, "TLSVersion") and hasattr(ssl_context, "minimum_version"):
                min_version = None
                if tls_version_str == "TLSV1_3":
                    min_version = ssl.TLSVersion.TLSv1_3
                elif tls_version_str == "TLSV1_2":
                    min_version = ssl.TLSVersion.TLSv1_2
                elif tls_version_str == "TLSV1_1":
                    min_version = ssl.TLSVersion.TLSv1_1
                
                if min_version:
                    ssl_context.minimum_version = min_version

            # Load custom certificates if provided
            ca_cert_path = self.config.get("ca_cert_path")
            if ca_cert_path:
                ssl_context.load_verify_locations(ca_cert_path)

            client_cert_path = self.config.get("client_cert_path")
            client_key_path = self.config.get("client_key_path")
            if client_cert_path and client_key_path:
                ssl_context.load_cert_chain(client_cert_path, client_key_path)

            return ssl_context
            
        except Exception as e:
            raise ConfigurationError(f"Failed to configure SSL/TLS: {e}", original_exception=e)

    def _validate_config(self) -> None:
        """Validate required configuration parameters."""
        if not self.odoo_url:
            raise ConfigurationError("odoo_url is required")
        if not self.database:
            raise ConfigurationError("database is required")
        if not self.username:
            raise ConfigurationError("username is required")
        if not self.password:
            raise ConfigurationError("api_key is required")

    async def authenticate_global(self) -> None:
        """Perform global authentication for the handler."""
        try:
            auth_result = await self._perform_authentication(
                self.username, self.password, self.database
            )
            
            if not auth_result:
                raise AuthError("Global authentication failed")
                
            self.global_uid = auth_result
            self.global_password = self.password
            
            logger.info(f"Global authentication successful with UID: {self.global_uid}")
            
        except Exception as e:
            logger.error(f"Global authentication failed: {e}")
            raise AuthError(f"Global authentication failed: {e}")

    @abstractmethod
    async def _perform_authentication(
        self, username: str, password: str, database: str
    ) -> Union[int, bool, None]:
        """Perform authentication using the specific protocol implementation."""
        pass

    @abstractmethod
    async def execute_kw(
        self, model: str, method: str, args: List = None, kwargs: Dict = None
    ) -> Any:
        """Execute a method on a model using the specific protocol."""
        pass

    @abstractmethod
    async def call(self, service: str, method: str, args: list) -> Any:
        """Make a direct call to a service method."""
        pass

    def _make_hashable(self, obj: Any) -> Any:
        """Convert an object to a hashable form for caching."""
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        elif isinstance(obj, (list, tuple)):
            return tuple(self._make_hashable(item) for item in obj)
        elif isinstance(obj, dict):
            return tuple(sorted((k, self._make_hashable(v)) for k, v in obj.items()))
        else:
            # For other types, convert to string
            return str(obj)

    # Common read methods that are typically cacheable
    READ_METHODS = {
        "read", "search", "search_read", "search_count", 
        "fields_get", "default_get", "name_search"
    }

    def is_read_method(self, service: str, method: str) -> bool:
        """Check if a method is a read operation that can be cached."""
        return service == "object" and method in self.READ_METHODS

    async def cleanup(self) -> None:
        """Clean up resources used by the handler."""
        # Override in subclasses if needed
        pass
