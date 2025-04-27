from xmlrpc.client import ServerProxy, Fault, ProtocolError as XmlRpcProtocolError
# Corrected imports - ensure all needed types from typing are imported
from typing import Dict, Any, Optional, List, Tuple, Set, Union
from odoo_mcp.error_handling.exceptions import AuthError, NetworkError, ProtocolError, OdooMCPError, ConfigurationError, OdooValidationError, OdooRecordNotFoundError
from odoo_mcp.performance.caching import cache_manager, CACHE_TYPE # Import cache manager
import socket
import logging
import ssl # Import ssl module

logger = logging.getLogger(__name__)

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

        common_url = f'{self.odoo_url}/xmlrpc/2/common'
        models_url = f'{self.odoo_url}/xmlrpc/2/object'
        ssl_context: Optional[ssl.SSLContext] = None

        # --- Configure SSL/TLS Context ---
        if self.odoo_url.startswith('https://'):
            try:
                tls_version_str = config.get('tls_version', 'TLSv1.3').upper().replace('.', '_')
                protocol_version = ssl.PROTOCOL_TLS_CLIENT
                ssl_context = ssl.SSLContext(protocol_version)
                ssl_context.check_hostname = True
                ssl_context.verify_mode = ssl.CERT_REQUIRED

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
            self.common = ServerProxy(common_url, context=ssl_context)
            self.models = ServerProxy(models_url, context=ssl_context)
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
        # Corrected order: Catch specific network/protocol errors first
        except (XmlRpcProtocolError, socket.gaierror, ConnectionRefusedError, OSError) as e:
             raise NetworkError(f"Failed to connect or authenticate via XML-RPC at {common_url}: {e}", original_exception=e)
        except Exception as e: # Catch other exceptions last
             raise OdooMCPError(f"Unexpected error during XMLRPCHandler initialization: {e}", original_exception=e)

    READ_METHODS = {'read', 'search', 'search_read', 'search_count', 'fields_get', 'default_get'}

    # Removing Optional type hints as a workaround for persistent NameError
    def execute_kw(self, model: str, method: str, args: list, kwargs: dict, uid = None, password = None) -> Any:
         """
         Execute a method on an Odoo model via XML-RPC.
         Handles caching for read methods and uses provided or global credentials.
         """
         call_uid = uid if uid is not None else self.config.get('uid')
         call_password = password if password is not None else self.config.get('api_key')

         if call_uid is None or call_password is None:
              if not hasattr(self, 'global_uid'):
                   try:
                        logger.info("Fetching global UID for handler...")
                        auth_user = self.config.get('username')
                        auth_pass = self.config.get('api_key')
                        if not auth_user or not auth_pass:
                             raise AuthError("Missing global username/api_key in config for initial handler authentication.")
                        # Ensure args passed to authenticate are hashable for mock
                        self.global_uid = self.common.authenticate(self.database, auth_user, auth_pass, {})
                        self.global_password = auth_pass
                        if not self.global_uid: raise AuthError("Failed to authenticate with global credentials.")
                   except Exception as auth_e:
                        # Catch potential TypeError from mock due to unhashable args
                        if isinstance(auth_e, TypeError) and "unhashable type" in str(auth_e):
                             logger.error(f"Internal error: Unhashable type passed to mock authenticate: {auth_e}")
                        raise AuthError(f"execute_kw requires UID/Password, and failed to get global credentials: {auth_e}", original_exception=auth_e)
              call_uid = self.global_uid
              call_password = self.global_password

         if method in self.READ_METHODS and cache_manager:
              logger.debug(f"Cacheable method detected: {model}.{method}. Attempting cache lookup.")
              try:
                   hashable_args = self._make_hashable(args)
                   hashable_kwargs = self._make_hashable(kwargs) # Corrected call
              except TypeError as e:
                   logger.warning(f"Could not make arguments hashable for caching {model}.{method}: {e}. Executing directly.")
                   return self._execute_kw_direct(model, method, args, kwargs, call_uid, call_password)

              if CACHE_TYPE == 'cachetools':
                   return self._execute_kw_cached(model, method, hashable_args, hashable_kwargs, call_uid, call_password)
              else:
                   logger.debug("Executing non-TTL cached or uncached read method (cachetools unavailable).")
                   return self._execute_kw_direct(model, method, args, kwargs, call_uid, call_password)
         else:
              logger.debug(f"Executing non-cacheable method: {model}.{method}")
              return self._execute_kw_direct(model, method, args, kwargs, call_uid, call_password)

    def _execute_kw_direct(self, model: str, method: str, args: list, kwargs: dict, uid: int, password: str) -> Any:
         """Directly execute the XML-RPC call to Odoo without using any cache."""
         try:
              logger.debug(f"Executing XML-RPC: model={model}, method={method}, uid={uid}")
              result = self.models.execute_kw(self.database, uid, password, model, method, args, kwargs)
              logger.debug(f"XML-RPC call successful for {model}.{method}")
              return result
         except Fault as e:
              fault_string = e.faultString
              logger.warning(f"XML-RPC Fault during {model}.{method}: {fault_string}")

              # Map specific Odoo errors based on faultString content
              if "AccessDenied" in fault_string or "AccessError" in fault_string or "authenticate" in fault_string:
                   raise AuthError(f"Odoo Access Denied/Error: {fault_string}", original_exception=e)
              elif "UserError" in fault_string or "ValidationError" in fault_string:
                   # Extract cleaner message if possible (Odoo often includes traceback)
                   clean_message = fault_string.split('\n')[0] # Basic cleaning
                   raise OdooValidationError(f"Odoo Validation Error: {clean_message}", original_exception=e)
              elif "Record does not exist" in fault_string or "Missing record" in fault_string:
                   raise OdooRecordNotFoundError(f"Odoo Record Not Found: {fault_string}", original_exception=e)
              # Add more specific mappings here if needed
              else:
                   # Fallback for other Odoo/XML-RPC errors
                   raise ProtocolError(f"Odoo XML-RPC Execution Fault: {fault_string}", original_exception=e)
         except (XmlRpcProtocolError, socket.gaierror, ConnectionRefusedError, OSError) as e:
              logger.error(f"Network/Protocol error during {model}.{method}: {e}")
              raise NetworkError(f"Network or protocol error during XML-RPC call: {e}", original_exception=e)
         except Exception as e:
              logger.exception(f"Unexpected error during {model}.{method}")
              raise OdooMCPError(f"Unexpected error during XML-RPC execute_kw: {e}", original_exception=e)

    @cache_manager.get_ttl_cache_decorator(cache_instance=cache_manager.odoo_read_cache if cache_manager and CACHE_TYPE == 'cachetools' else None)
    def _execute_kw_cached(self, model: str, method: str, args: tuple, kwargs_tuple: tuple, uid: int, password: str) -> Any:
         """Wrapper method for cached execution using cachetools."""
         kwargs_dict = dict(kwargs_tuple)
         logger.debug(f"Executing CACHED XML-RPC call wrapper for {model}.{method} (UID: {uid})")
         return self._execute_kw_direct(model, method, list(args), kwargs_dict, uid, password)

    def _make_hashable(self, item: Any) -> Union[tuple, Any]:
        """
        Recursively convert mutable collection types (list, dict, set)
        into immutable, hashable types (tuple).
        """
        if isinstance(item, dict):
            return tuple(sorted((k, self._make_hashable(v)) for k, v in item.items()))
        elif isinstance(item, list):
            return tuple(self._make_hashable(i) for i in item)
        elif isinstance(item, set):
            return tuple(sorted(self._make_hashable(i) for i in item))
        # For other types, attempt to hash directly. If it fails, raise TypeError.
        try:
            hash(item)
            return item
        except TypeError as e:
            logger.error(f"Attempted to hash unhashable type: {type(item).__name__}")
            # Re-raise the TypeError with a more informative message
            raise TypeError(f"Object of type {type(item).__name__} is not hashable and cannot be used in cache key") from e
