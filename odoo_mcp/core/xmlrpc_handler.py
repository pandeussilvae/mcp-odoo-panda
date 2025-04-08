from xmlrpc.client import ServerProxy, Fault, ProtocolError as XmlRpcProtocolError
# Corrected imports - ensure all needed types from typing are imported
from typing import Dict, Any, Optional, List, Tuple, Set, Union # Added Union
from odoo_mcp.error_handling.exceptions import AuthError, NetworkError, ProtocolError, OdooMCPError, ConfigurationError
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
                # Map common TLS version strings to ssl constants
                # Note: PROTOCOL_TLS_CLIENT uses highest available protocol by default
                # Forcing TLS 1.3 might require OpenSSL 1.1.1+
                # Forcing TLS 1.2: ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
                protocol_version = ssl.PROTOCOL_TLS_CLIENT

                ssl_context = ssl.SSLContext(protocol_version)
                ssl_context.check_hostname = True
                ssl_context.verify_mode = ssl.CERT_REQUIRED

                # --- Attempt to enforce specific TLS version ---
                # Method 1: Using minimum_version (preferred, requires Python 3.7+ & recent OpenSSL)
                min_version_set = False
                if hasattr(ssl, 'TLSVersion') and hasattr(ssl_context, 'minimum_version'):
                    min_version = None
                    if tls_version_str == 'TLSV1_3':
                        min_version = ssl.TLSVersion.TLSv1_3
                    elif tls_version_str == 'TLSV1_2':
                        min_version = ssl.TLSVersion.TLSv1_2
                    # Add other versions if needed

                    if min_version:
                        try:
                            ssl_context.minimum_version = min_version
                            logger.info(f"Set minimum TLS version to {min_version.name} for XMLRPC.")
                            min_version_set = True
                        except (ValueError, OSError) as e: # OSError if version not supported by system OpenSSL
                            logger.warning(f"Could not set minimum TLS version to {min_version.name} via minimum_version: {e}")
                    else:
                         logger.warning(f"TLS version '{config.get('tls_version')}' not directly mappable to ssl.TLSVersion enum.")

                # Method 2: Using options (fallback, less precise)
                if not min_version_set:
                    logger.info("Attempting to set TLS version using context options (fallback).")
                    # Disable protocols older than the desired one.
                    # Note: This disables *specific* older versions, doesn't guarantee the desired one is used if newer exists.
                    options = ssl.OP_NO_SSLv3 # Always disable SSLv3
                    if tls_version_str == 'TLSV1_3':
                        options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | ssl.OP_NO_TLSv1_2
                        logger.info("Attempting to disable TLSv1, TLSv1.1, TLSv1.2 for XMLRPC.")
                    elif tls_version_str == 'TLSV1_2':
                        options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
                        # Also disable TLSv1.3 if possible/desired (might prevent connection if server *only* supports 1.3)
                        # options |= getattr(ssl, 'OP_NO_TLSv1_3', 0)
                        logger.info("Attempting to disable TLSv1, TLSv1.1 for XMLRPC.")
                    else:
                         logger.warning(f"Cannot enforce unsupported TLS version '{config.get('tls_version')}' using options. Using system defaults.")
                         # Reset options to default secure ones if needed? Or just rely on PROTOCOL_TLS_CLIENT defaults.
                         options = 0 # Rely on context default

                    if options != 0:
                         ssl_context.options |= options

                # TODO: Add support for custom CA certs or client certs from config if needed
                # ssl_context.load_verify_locations(cafile=config.get('ca_cert_path'))
                # ssl_context.load_cert_chain(certfile=config.get('client_cert_path'), keyfile=config.get('client_key_path'))

            except Exception as e:
                 logger.error(f"Failed to create SSL context for XMLRPC: {e}", exc_info=True)
                 raise ConfigurationError(f"Failed to configure TLS for XMLRPC: {e}", original_exception=e)

        # --- Create ServerProxy Instances ---
        try:
            self.common = ServerProxy(common_url, context=ssl_context)
            self.models = ServerProxy(models_url, context=ssl_context)
            # Do not authenticate during initialization
            # self.uid = self.common.authenticate(self.database, self.username, self.password, {})
            # Authentication will be per-call or handled by Authenticator/SessionManager logic
            logger.info("XMLRPCHandler initialized proxies for common and object endpoints.")
        except (XmlRpcProtocolError, socket.gaierror, ConnectionRefusedError, OSError) as e:
            # Still handle connection errors during proxy creation
             # Network or protocol errors during initial connection/auth
             raise NetworkError(f"Failed to connect or authenticate via XML-RPC at {common_url}: {e}", original_exception=e)
        except Exception as e:
             # Catch-all for unexpected errors during init
             # Use OdooMCPError defined in exceptions module
             raise OdooMCPError(f"Unexpected error during XMLRPCHandler initialization: {e}", original_exception=e)

    # Apply caching conditionally based on the method name
    # This is a basic example; more sophisticated logic might be needed
    # based on method arguments or model type.
    # Note: Caching write operations (create, write, unlink) is generally wrong!
    # Note: functools.lru_cache doesn't work directly on async methods or methods of classes easily without wrappers.
    #       cachetools handles instance methods better. We'll use the cache_manager decorator.

    # Define methods that are generally safe to cache
    READ_METHODS = {'read', 'search', 'search_read', 'search_count', 'fields_get', 'default_get'}

    # Use the cache manager's decorator
    # Apply to the main execution method, but the caching logic inside will decide
    # We need an async wrapper if the underlying call becomes async, but ServerProxy is sync.
    # Let's create a wrapper method that decides whether to cache or not.

    # Removing Optional type hints as a workaround for persistent NameError
    def execute_kw(self, model: str, method: str, args: list, kwargs: dict, uid = None, password = None) -> Any:
         """
         Execute a method on an Odoo model via XML-RPC.

         Handles caching for read methods (if cachetools is available) and uses
         provided or global credentials for the Odoo call.

         Args:
             model: The name of the Odoo model.
             method: The name of the method to execute on the model.
             args: A list of positional arguments for the method.
             kwargs: A dictionary of keyword arguments for the method.
             uid: The Odoo user ID to use for the call. If None, attempts to use
                  global UID fetched using config credentials.
             password: The Odoo password or API key for the user. If None, attempts
                       to use global password from config credentials.

         Returns:
             The result returned by the Odoo method.

         Raises:
             AuthError: If authentication fails (either explicitly or when fetching global UID).
             NetworkError: If there's a network issue during the call.
             ProtocolError: If Odoo returns an XML-RPC fault (non-auth related).
             OdooMCPError: For other unexpected errors.
             TypeError: If args/kwargs cannot be made hashable for caching.
         """
         # Use provided credentials or fall back to config credentials
         call_uid = uid if uid is not None else self.config.get('uid') # Need to store uid from config if using global
         call_password = password if password is not None else self.config.get('api_key')

         # We need UID/Password for the actual call, even for reads usually in Odoo
         if call_uid is None or call_password is None:
              # If we operate globally, uid might be fetched once and stored in config/handler state
              # For now, assume they must be available from config if not passed explicitly.
              # Let's try fetching global UID if not present (requires config user/pass)
              if not hasattr(self, 'global_uid'):
                   try:
                        logger.info("Fetching global UID for handler...")
                        # Ensure uid/password used for this internal auth call are correct
                        auth_user = self.config.get('username')
                        auth_pass = self.config.get('api_key')
                        if not auth_user or not auth_pass:
                             raise AuthError("Missing global username/api_key in config for initial handler authentication.")
                        self.global_uid = self.common.authenticate(self.database, auth_user, auth_pass, {})
                        self.global_password = auth_pass # Store the password used
                        if not self.global_uid: raise AuthError("Failed to authenticate with global credentials.")
                        # Store fetched global UID back into config dict for potential reuse? Or just handler state?
                        # self.config['uid'] = self.global_uid # Be careful modifying config dict
                   except Exception as auth_e:
                        raise AuthError(f"execute_kw requires UID/Password, and failed to get global credentials: {auth_e}", original_exception=auth_e)
              call_uid = self.global_uid
              call_password = self.global_password


         if method in self.READ_METHODS and cache_manager:
              logger.debug(f"Cacheable method detected: {model}.{method}. Attempting cache lookup.")
              # Pass credentials to cached/direct methods
              # Use the appropriate decorator based on availability
              # Convert args/kwargs to hashable tuples for caching key
              try:
                   hashable_args = self._make_hashable(args)
                   hashable_kwargs = tuple(sorted(self._make_hashable(kwargs).items()))
              except TypeError as e:
                   logger.warning(f"Could not make arguments hashable for caching {model}.{method}: {e}. Executing directly.")
                   return self._execute_kw_direct(model, method, args, kwargs, call_uid, call_password)

              if CACHE_TYPE == 'cachetools':
                   # Pass hashable versions to the cached method
                   # Ensure call_uid and call_password are passed correctly
                   return self._execute_kw_cached(model, method, hashable_args, hashable_kwargs, call_uid, call_password)
              else:
                   logger.debug("Executing non-TTL cached or uncached read method (cachetools unavailable).")
                   # LRU cache fallback would need similar decoration on a helper
                   return self._execute_kw_direct(model, method, args, kwargs, call_uid, call_password)
         else:
              logger.debug(f"Executing non-cacheable method: {model}.{method}")
              return self._execute_kw_direct(model, method, args, kwargs, call_uid, call_password)


    # Helper method for direct execution (no cache)
    def _execute_kw_direct(self, model: str, method: str, args: list, kwargs: dict, uid: int, password: str) -> Any:
         """
         Directly execute the XML-RPC call to Odoo without using any cache.

         This method contains the actual `models.execute_kw` call and its specific
         error handling logic.

         Args:
             model: The Odoo model name.
             method: The Odoo method name.
             args: Positional arguments for the Odoo method.
             kwargs: Keyword arguments for the Odoo method.
             uid: The user ID for authentication.
             password: The password/API key for authentication.

         Returns:
             The result from the Odoo method.

         Raises:
             AuthError: If Odoo returns an authentication/access error.
             ProtocolError: If Odoo returns other XML-RPC faults.
             NetworkError: For network-level errors during the call.
             OdooMCPError: For other unexpected errors.
         """
         try:
              # Consider masking args/kwargs before logging if they might contain sensitive data
              logger.debug(f"Executing XML-RPC: model={model}, method={method}, uid={uid}") # Log args/kwargs separately if needed after masking
              result = self.models.execute_kw(self.database, uid, password, model, method, args, kwargs)
              logger.debug(f"XML-RPC call successful for {model}.{method}")
              return result
         except Fault as e:
              logger.warning(f"XML-RPC Fault during {model}.{method}: {e.faultString}")
              if "AccessDenied" in e.faultString or "AccessError" in e.faultString or "authenticate" in e.faultString:
                   raise AuthError(f"Odoo Access Denied/Error: {e.faultString}", original_exception=e)
              else:
                   raise ProtocolError(f"Odoo XML-RPC Execution Fault: {e.faultString}", original_exception=e)
         except (XmlRpcProtocolError, socket.gaierror, ConnectionRefusedError, OSError) as e:
              logger.error(f"Network/Protocol error during {model}.{method}: {e}")
              raise NetworkError(f"Network or protocol error during XML-RPC call: {e}", original_exception=e)
         except Exception as e:
              logger.exception(f"Unexpected error during {model}.{method}")
              raise OdooMCPError(f"Unexpected error during XML-RPC execute_kw: {e}", original_exception=e)


    # Helper method decorated with cachetools TTL cache (if available)
    @cache_manager.get_ttl_cache_decorator(cache_instance=cache_manager.odoo_read_cache if cache_manager and CACHE_TYPE == 'cachetools' else None)
    def _execute_kw_cached(self, model: str, method: str, args: tuple, kwargs_tuple: tuple, uid: int, password: str) -> Any:
         """
         Wrapper method for cached execution using cachetools.

         This method is decorated by the TTL cache decorator. It calls the direct
         execution method `_execute_kw_direct`. The cache key is automatically
         generated by `cachetools.keys.hashkey` based on all arguments except `self`.
         Crucially, the `password` argument is included here but should NOT affect the
         cache key generation if `hashkey` is used correctly (it hashes based on value).
         However, for safety and clarity, one might exclude password explicitly if needed.
         The UID *is* included in the key, ensuring user-specific results are cached separately.

         Args:
             model: The Odoo model name.
             method: The Odoo method name.
             args: Hashable tuple of positional arguments.
             kwargs_tuple: Hashable tuple of keyword argument items (key, value).
             uid: The user ID (part of the cache key).
             password: The password/API key (used for the call, ideally not in cache key).

         Returns:
             The result from `_execute_kw_direct`, potentially from cache.
         """
         # Convert hashable kwargs tuple back to dict for the actual call
         kwargs_dict = dict(kwargs_tuple)
         logger.debug(f"Executing CACHED XML-RPC call wrapper for {model}.{method} (UID: {uid})")
         # The decorator caches the result of calling _execute_kw_direct with these args
         return self._execute_kw_direct(model, method, list(args), kwargs_dict, uid, password)


    # Helper to make nested structures hashable for caching keys
    def _make_hashable(self, item: Any) -> Union[tuple, Any]:
        """
        Recursively convert mutable collection types (list, dict, set)
        into immutable, hashable types (tuple).

        Args:
            item: The item to potentially convert.

        Returns:
            A hashable version of the item (e.g., tuple for lists/dicts/sets)
            or the original item if already hashable.
        """
        if isinstance(item, dict):
            # Convert dict to sorted tuple of (key, hashable_value) pairs
            return tuple(sorted((k, self._make_hashable(v)) for k, v in item.items()))
        elif isinstance(item, list):
            # Convert list to tuple of hashable items
            return tuple(self._make_hashable(i) for i in item)
        elif isinstance(item, set):
            # Convert set to sorted tuple of hashable items
            return tuple(sorted(self._make_hashable(i) for i in item))
        # Assume other types (int, str, bool, tuple, None, etc.) are hashable
        return item


    # --- Original execute_kw method's error handling (now in _execute_kw_direct) ---
    #   try:
    #       result = self.models.execute_kw(self.database, self.uid, self.password, model, method, args, kwargs)
    #       return result
    #   except Fault as e:
    #       # Handle specific Odoo/XML-RPC errors
    #       # Check if it's an access error (might indicate session expiry or rights issue)
    #       if "AccessDenied" in e.faultString or "AccessError" in e.faultString:
    #            raise AuthError(f"Odoo Access Denied/Error: {e.faultString}", original_exception=e)
    #       else:
    #            raise ProtocolError(f"Odoo XML-RPC Execution Fault: {e.faultString}", original_exception=e)
    #   except (XmlRpcProtocolError, socket.gaierror, ConnectionRefusedError, OSError) as e:
    #        # Network or protocol errors during execution
    #        raise NetworkError(f"Network or protocol error during XML-RPC call: {e}", original_exception=e)
    #   except Exception as e:
    #       # Catch-all for unexpected errors during execution
    #       raise OdooMCPError(f"Unexpected error during XML-RPC execute_kw: {e}", original_exception=e)
