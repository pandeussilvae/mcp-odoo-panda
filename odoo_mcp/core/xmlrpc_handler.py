from xmlrpc.client import ServerProxy, Fault, ProtocolError as XmlRpcProtocolError
# Corrected imports - ensure all needed types from typing are imported
from typing import Dict, Any, Optional, List, Tuple, Set, Union
from odoo_mcp.error_handling.exceptions import AuthError, NetworkError, ProtocolError, OdooMCPError, ConfigurationError, OdooValidationError, OdooRecordNotFoundError
from odoo_mcp.performance.caching import get_cache_manager, CACHE_TYPE, initialize_cache_manager
import socket
import logging
import ssl # Import ssl module
import sys
from functools import wraps
import asyncio

logger = logging.getLogger(__name__)

def safe_cache_decorator(func):
    """Safe wrapper for cache decorator that handles None cache_manager."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            cache_manager = get_cache_manager()
            if cache_manager and CACHE_TYPE == 'cachetools':
                cache_decorator = cache_manager.get_ttl_cache_decorator(
                    cache_instance=cache_manager.odoo_read_cache
                )
                return await cache_decorator(func)(*args, **kwargs)
        except ConfigurationError:
            logger.warning("Cache manager not initialized, executing without cache")
        return await func(*args, **kwargs)
    return wrapper

class XMLRPCHandler:
    """
    Handles communication with Odoo using the XML-RPC protocol.

    Manages ServerProxy instances for common and object endpoints and provides
    a method to execute model methods, incorporating caching for read operations.
    """
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the XMLRPCHandler.

        Creates ServerProxy instances for Odoo's common and object XML-RPC endpoints.
        Does not perform authentication during initialization; authentication details
        are expected per call or retrieved from config if needed.

        Args:
            config: The server configuration dictionary. Requires 'odoo_url',
                    'database', 'username', 'api_key'.

        Raises:
            NetworkError: If creating the ServerProxy instances fails due to
                          connection or protocol issues.
            OdooMCPError: For other unexpected errors during initialization.
        """
        self.config = config
        self.odoo_url = config.get('odoo_url')
        self.database = config.get('database')
        self.username = config.get('username')
        self.password = config.get('api_key')

        # Initialize cache manager if not already initialized
        try:
            get_cache_manager()
        except ConfigurationError:
            initialize_cache_manager(config)

        common_url = f'{self.odoo_url}/xmlrpc/2/common'
        models_url = f'{self.odoo_url}/xmlrpc/2/object'
        ssl_context: Optional[ssl.SSLContext] = None

        # Configure SSL/TLS Context
        if self.odoo_url.startswith('https://'):
            try:
                tls_version_str = config.get('tls_version', 'TLSv1.3').upper().replace('.', '_')
                protocol_version = ssl.PROTOCOL_TLS_CLIENT
                ssl_context = ssl.SSLContext(protocol_version)
                ssl_context.check_hostname = True
                ssl_context.verify_mode = ssl.CERT_REQUIRED
                ssl_context.load_default_certs()

                min_version_set = False
                if hasattr(ssl, 'TLSVersion') and hasattr(ssl_context, 'minimum_version'):
                    min_version = None
                    if tls_version_str == 'TLSV1_3':
                        min_version = ssl.TLSVersion.TLSv1_3
                    elif tls_version_str == 'TLSV1_2':
                        min_version = ssl.TLSVersion.TLSv1_2

                    if min_version:
                        try:
                            ssl_context.minimum_version = min_version
                            logger.info(f"Set minimum TLS version to {min_version.name} for XMLRPC.")
                            min_version_set = True
                        except (ValueError, OSError) as e:
                            logger.warning(f"Could not set minimum TLS version to {min_version.name} via minimum_version: {e}")
                    else:
                         logger.warning(f"TLS version '{config.get('tls_version')}' not directly mappable to ssl.TLSVersion enum.")

                if not min_version_set:
                    logger.info("Attempting to set TLS version using context options (fallback).")
                    options = ssl.OP_NO_SSLv3
                    if tls_version_str == 'TLSV1_3':
                        options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | ssl.OP_NO_TLSv1_2
                        logger.info("Attempting to disable TLSv1, TLSv1.1, TLSv1.2 for XMLRPC.")
                    elif tls_version_str == 'TLSV1_2':
                        options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
                        logger.info("Attempting to disable TLSv1, TLSv1.1 for XMLRPC.")
                    else:
                         logger.warning(f"Cannot enforce unsupported TLS version '{config.get('tls_version')}' using options. Using system defaults.")
                         options = 0

                    if options != 0:
                         ssl_context.options |= options

            except Exception as e:
                 logger.error(f"Failed to create SSL context for XMLRPC: {e}", exc_info=True)
                 raise ConfigurationError(f"Failed to configure TLS for XMLRPC: {e}", original_exception=e)

        # --- Create ServerProxy Instances ---
        try:
            self.common = ServerProxy(common_url, context=ssl_context, allow_none=True)
            self.models = ServerProxy(models_url, context=ssl_context, allow_none=True)
            logger.info("XMLRPCHandler initialized proxies for common and object endpoints.")
            # Autenticazione globale per log di connessione riuscita
            try:
                auth_user = self.username
                auth_pass = self.password
                if not auth_user or not auth_pass:
                    raise AuthError("Missing global username/api_key in config for initial handler authentication.")
                self.global_uid = self.common.authenticate(self.database, auth_user, auth_pass, {})
                self.global_password = auth_pass
                if not self.global_uid:
                    raise AuthError("Failed to authenticate with global credentials.")
                logger.info(f"Successfully connected to Odoo at {self.odoo_url} (db: {self.database}, user: {self.username})")
            except Exception as auth_e:
                logger.error(f"Failed to authenticate with Odoo during handler init: {auth_e}")
                raise AuthError(f"Authentication failed during handler initialization: {auth_e}")
        except (XmlRpcProtocolError, socket.gaierror, ConnectionRefusedError, OSError) as e:
             raise NetworkError(f"Failed to connect or authenticate via XML-RPC at {common_url}: {e}", original_exception=e)
        except Exception as e:
             raise OdooMCPError(f"Unexpected error during XMLRPCHandler initialization: {e}", original_exception=e)

    READ_METHODS = {'read', 'search', 'search_read', 'search_count', 'fields_get', 'default_get'}

    @safe_cache_decorator
    async def execute_kw(self, model: str, method: str, args: List = None, kwargs: Dict = None) -> Any:
        """
        Execute a method on a model with keyword arguments.

        Args:
            model: Model name
            method: Method name
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            Any: Method result
        """
        try:
            # Run the synchronous XML-RPC call in a thread pool
            loop = asyncio.get_event_loop()
            proxy = ServerProxy(f"{self.odoo_url}/xmlrpc/2/object")
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda: proxy.execute_kw(
                    self.database,
                    self.global_uid,
                    self.global_password,
                    model,
                    method,
                    args or [],
                    kwargs or {}
                )
                )
                return result
            finally:
                proxy.close()
        except Fault as e:
            logger.error(f"XML-RPC Fault: {str(e)}")
            raise ProtocolError(f"XML-RPC Fault: {str(e)}")
        except Exception as e:
            logger.error(f"Error executing XML-RPC method: {str(e)}")
            raise NetworkError(f"Error executing XML-RPC method: {str(e)}")
