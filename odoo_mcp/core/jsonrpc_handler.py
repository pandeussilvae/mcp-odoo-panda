import httpx # Import httpx
import json
import logging
import asyncio
import ssl # Import ssl for context creation
from typing import Dict, Any, Optional

from odoo_mcp.error_handling.exceptions import NetworkError, ProtocolError, OdooMCPError, AuthError, ConfigurationError
from odoo_mcp.performance.caching import cache_manager, CACHE_TYPE

logger = logging.getLogger(__name__)

class JSONRPCHandler:
    """
    Handles communication with Odoo using the JSON-RPC protocol via HTTPX.

    Manages an asynchronous HTTP client session using `httpx.AsyncClient` and
    provides a method to execute RPC calls, incorporating caching for read operations.
    """
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the JSONRPCHandler.

        Sets up the base URL and an `httpx.AsyncClient` for making async HTTP calls.
        Configures TLS based on the provided configuration.

        Args:
            config: The server configuration dictionary. Requires 'odoo_url', 'database'.
                    Optional TLS keys: 'tls_version', 'ca_cert_path',
                    'client_cert_path', 'client_key_path'.

        Raises:
            ConfigurationError: If TLS configuration fails.
        """
        self.config = config
        self.odoo_url = config.get('odoo_url')
        self.jsonrpc_url = f"{self.odoo_url}/jsonrpc"
        self.database = config.get('database')

        # --- Configure HTTPX AsyncClient with TLS ---
        verify: Union[str, bool, ssl.SSLContext] = True
        cert: Optional[Union[str, Tuple[str, str]]] = None
        ssl_context: Optional[ssl.SSLContext] = None

        if self.odoo_url.startswith('https://'):
            logger.info("Configuring TLS for JSONRPC handler (httpx client).")
            ca_cert_path = config.get('ca_cert_path')
            if ca_cert_path:
                verify = ca_cert_path
                logger.info(f"JSONRPC using custom CA bundle: {ca_cert_path}")
            else:
                verify = True # Default: Use certifi or system CAs
                logger.info("JSONRPC using default CA bundle for TLS verification.")

            client_cert_path = config.get('client_cert_path')
            client_key_path = config.get('client_key_path')
            if client_cert_path and client_key_path:
                cert = (client_cert_path, client_key_path)
                logger.info(f"JSONRPC using client certificate: {client_cert_path}")
            elif client_cert_path:
                cert = client_cert_path
                logger.info(f"JSONRPC using client certificate (key assumed within): {client_cert_path}")

            # Attempt to configure specific TLS version using SSLContext
            # httpx allows passing an SSLContext directly to verify
            try:
                tls_version_str = config.get('tls_version', 'TLSv1.3').upper().replace('.', '_')
                protocol_version = ssl.PROTOCOL_TLS_CLIENT
                context = ssl.SSLContext(protocol_version)
                context.check_hostname = True
                # Load default CAs unless a custom one is specified
                if isinstance(verify, bool) and verify:
                     context.load_default_certs(ssl.Purpose.SERVER_AUTH)
                elif isinstance(verify, str):
                     context.load_verify_locations(cafile=verify)

                # Set minimum TLS version (best effort)
                min_version_set = False
                if hasattr(ssl, 'TLSVersion') and hasattr(context, 'minimum_version'):
                    min_version = getattr(ssl.TLSVersion, tls_version_str, None)
                    if min_version:
                        try:
                            context.minimum_version = min_version
                            logger.info(f"Set minimum TLS version to {min_version.name} for httpx.")
                            min_version_set = True
                        except (ValueError, OSError) as e:
                            logger.warning(f"Could not set minimum TLS version {tls_version_str} via minimum_version: {e}")
                    else:
                        logger.warning(f"TLS version '{config.get('tls_version')}' not mappable to ssl.TLSVersion.")

                if not min_version_set:
                    logger.info("Attempting to set TLS version using context options (fallback).")
                    options = ssl.OP_NO_SSLv3
                    if tls_version_str == 'TLSV1_3': options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | ssl.OP_NO_TLSv1_2
                    elif tls_version_str == 'TLSV1_2': options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
                    else: options = 0 # Rely on default
                    if options != 0: context.options |= options

                # Load client cert into context if specified
                if cert:
                     if isinstance(cert, tuple):
                          context.load_cert_chain(certfile=cert[0], keyfile=cert[1])
                     else:
                          context.load_cert_chain(certfile=cert)

                ssl_context = context
                verify = ssl_context # Use the configured context for verification
                logger.info("Using custom SSLContext for httpx TLS configuration.")

            except Exception as e:
                 logger.error(f"Failed to create SSL context for httpx: {e}", exc_info=True)
                 raise ConfigurationError(f"Failed to configure TLS for httpx: {e}", original_exception=e)

        # Create the AsyncClient
        # Consider adding timeout configuration from self.config
        request_timeout = self.config.get('timeout', 30)
        self.async_client = httpx.AsyncClient(verify=verify, cert=cert, timeout=request_timeout)
        logger.info(f"httpx.AsyncClient initialized. Verify={type(verify)}, Cert={cert is not None}, Timeout={request_timeout}s")


    def _prepare_payload(self, method: str, params: dict) -> dict:
        """Prepare the standard JSON-RPC 2.0 payload structure."""
        return {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": None, # Or generate unique IDs
        }

    READ_METHODS = {'call'} # Assume 'call' with specific service/method might be readable

    async def call(self, service: str, method: str, args: list) -> Any:
        """
        Make a JSON-RPC call to the Odoo instance using httpx.

        Handles caching for potentially cacheable read methods.

        Args:
            service: The target service name (e.g., 'object').
            method: The method to call on the service.
            args: A list of arguments for the method.

        Returns:
            The result returned by the Odoo JSON-RPC method.

        Raises:
            AuthError, NetworkError, ProtocolError, OdooMCPError, TypeError.
        """
        is_cacheable = service == 'object' and method in {'read', 'search', 'search_read', 'search_count', 'fields_get', 'default_get'}

        if is_cacheable and cache_manager:
            logger.debug(f"Cacheable JSON-RPC method detected: {service}.{method}. Attempting cache lookup.")
            try:
                hashable_args = self._make_hashable(args)
            except TypeError as e:
                 logger.warning(f"Could not make arguments hashable for caching {service}.{method}: {e}. Executing directly.")
                 return await self._call_direct(service, method, args)

            if CACHE_TYPE == 'cachetools':
                 return await self._call_cached(service, method, hashable_args)
            else:
                 logger.debug("Executing non-TTL cached or uncached JSON-RPC read method.")
                 return await self._call_direct(service, method, args)
        else:
            logger.debug(f"Executing non-cacheable JSON-RPC method: {service}.{method}")
            return await self._call_direct(service, method, args)


    async def _call_direct(self, service: str, method: str, args: list) -> Any:
         """
         Directly execute the JSON-RPC call to Odoo using httpx.

         Args:
             service: The target service name.
             method: The method name.
             args: List of arguments for the method.

         Returns:
             The result from the Odoo method.

         Raises:
             AuthError, ProtocolError, NetworkError, OdooMCPError.
         """
         payload_params = {
             "service": service,
             "method": method,
             # Assuming Odoo JSON-RPC expects db as first arg in the list
             "args": [self.database, *args]
             # TODO: Integrate session ID from SessionManager if needed
             # "context": {"session_id": session_id} # Example
         }
         payload = self._prepare_payload("call", payload_params)
         headers = {'Content-Type': 'application/json'}

         try:
             logger.debug(f"Executing JSON-RPC (httpx): service={service}, method={method}")
             response = await self.async_client.post(self.jsonrpc_url, headers=headers, json=payload)
             response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
             result = response.json()

             if result.get("error"):
                 error_data = result["error"]
                 error_message = error_data.get('message', 'Unknown JSON-RPC Error')
                 error_code = error_data.get('code')
                 error_debug_info = error_data.get('data', {}).get('debug', '')
                 full_error = f"Code {error_code}: {error_message} - {error_debug_info}".strip(" -")

                 # Map Odoo JSON-RPC error codes/messages to custom exceptions
                 # These codes might need adjustment based on Odoo version/specific errors
                 if error_code == 100 or "AccessDenied" in str(error_data) or "AccessError" in str(error_data):
                      raise AuthError(f"JSON-RPC Access Denied/Error: {full_error}", original_exception=Exception(str(error_data)))
                 else:
                      raise ProtocolError(f"JSON-RPC Error Response: {full_error}", original_exception=Exception(str(error_data)))

             return result.get("result")

         except httpx.TimeoutException as e:
             raise NetworkError(f"JSON-RPC request timed out after {self.async_client.timeout.read} seconds", original_exception=e)
         except httpx.ConnectError as e:
              raise NetworkError(f"JSON-RPC Connection Error: Unable to connect to {self.jsonrpc_url}", original_exception=e)
         except httpx.RequestError as e: # Catch other httpx request errors
             raise NetworkError(f"JSON-RPC Network/HTTP Error: {e}", original_exception=e)
         except json.JSONDecodeError as e:
              raise ProtocolError("Failed to decode JSON-RPC response", original_exception=e)
         except Exception as e:
              # Catch-all for unexpected errors during the call
              logger.exception(f"An unexpected error occurred during JSON-RPC call: {e}")
              raise OdooMCPError(f"An unexpected error occurred during JSON-RPC call: {e}", original_exception=e)


    @cache_manager.get_ttl_cache_decorator(cache_instance=cache_manager.odoo_read_cache if cache_manager and CACHE_TYPE == 'cachetools' else None)
    async def _call_cached(self, service: str, method: str, args: tuple) -> Any:
        """
        Wrapper method for cached execution using cachetools.
        Calls the direct execution method `_call_direct`.
        """
        logger.debug(f"Executing CACHED JSON-RPC call wrapper for {service}.{method}")
        # Pass args as a list as expected by _call_direct
        return await self._call_direct(service, method, list(args))

    # Helper to make nested structures hashable (can be shared or moved to utils)
    def _make_hashable(self, item: Any) -> Any:
        """Recursively convert mutable collection types into immutable, hashable types."""
        if isinstance(item, dict):
            return tuple(sorted((k, self._make_hashable(v)) for k, v in item.items()))
        elif isinstance(item, list):
            return tuple(self._make_hashable(i) for i in item)
        elif isinstance(item, set):
            return tuple(sorted(self._make_hashable(i) for i in item))
        try:
            hash(item)
            return item
        except TypeError as e:
            logger.error(f"Attempted to hash unhashable type: {type(item).__name__}")
            raise TypeError(f"Object of type {type(item).__name__} is not hashable and cannot be used in cache key") from e

    async def close(self):
        """Close the underlying httpx client session."""
        if hasattr(self, 'async_client'):
            await self.async_client.aclose()
            logger.info("httpx.AsyncClient closed.")
