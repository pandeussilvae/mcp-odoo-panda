import requests
import json
import logging
import asyncio
from typing import Dict, Any
from odoo_mcp.error_handling.exceptions import NetworkError, ProtocolError, OdooMCPError, AuthError # Import AuthError too
from odoo_mcp.performance.caching import cache_manager, CACHE_TYPE # Import cache manager

logger = logging.getLogger(__name__)

class JSONRPCHandler:
    """
    Handles communication with Odoo using the JSON-RPC protocol.

    Manages an HTTP session using `requests` and provides a method to execute
    RPC calls, incorporating caching for read operations.
    """
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the JSONRPCHandler.

        Sets up the base URL and a `requests.Session` for making HTTP calls.
        Note: Assumes JSON-RPC endpoint is at `/jsonrpc`. Authentication details
        (like session IDs) are expected to be handled per call or via session cookies.

        Args:
            config: The server configuration dictionary. Requires 'odoo_url', 'database'.
        """
        self.config = config
        self.odoo_url = config.get('odoo_url')
        self.session = requests.Session()
        self.jsonrpc_url = f"{self.odoo_url}/jsonrpc"
        # Authentication might be handled differently for JSON-RPC (e.g., session_id)
        # This basic implementation assumes public methods or separate auth handling
        self.database = config.get('database')

    def _prepare_payload(self, method: str, params: dict) -> dict:
        """Prepare the standard JSON-RPC 2.0 payload structure."""
        return {
            "jsonrpc": "2.0", # Standard JSON-RPC version
            "method": method,
            "params": params,
            "id": None,  # Or generate unique IDs if needed
        }

    # Define methods that are generally safe to cache for JSON-RPC
    # These might differ slightly from XML-RPC depending on API structure
    READ_METHODS = {'call'} # Assume 'call' with specific service/method might be readable

    # Apply caching conditionally
    async def call(self, service: str, method: str, args: list) -> Any:
        """
        Make a JSON-RPC call to the Odoo instance.

        Handles caching for potentially cacheable read methods and uses the
        internal `requests.Session` to perform the HTTP POST request.

        Args:
            service: The target service name (e.g., 'object').
            method: The method to call on the service.
            args: A list of arguments for the method. Note: Authentication details
                  might need to be included here depending on Odoo's JSON-RPC setup.

        Returns:
            The result returned by the Odoo JSON-RPC method.

        Raises:
            AuthError: If Odoo returns an authentication/access error.
            NetworkError: If there's a network issue during the call (timeout, connection error).
            ProtocolError: If the response is invalid JSON or a non-auth JSON-RPC error occurs.
            OdooMCPError: For other unexpected errors.
            TypeError: If args cannot be made hashable for caching.
        """
        # Basic check: Assume calls to 'object' service with methods like 'read', 'search' are cacheable
        # More robust check needed based on actual JSON-RPC usage patterns.
        is_cacheable = service == 'object' and method in {'read', 'search', 'search_read', 'search_count', 'fields_get', 'default_get'}

        if is_cacheable and cache_manager:
            logger.debug(f"Cacheable JSON-RPC method detected: {service}.{method}. Attempting cache lookup.")
            if CACHE_TYPE == 'cachetools':
                 # Call the cached helper method
                 return await self._call_cached(service, method, args)
            else:
                 logger.debug("Executing non-TTL cached or uncached JSON-RPC read method.")
                 return await self._call_direct(service, method, args)
        else:
            logger.debug(f"Executing non-cacheable JSON-RPC method: {service}.{method}")
            return await self._call_direct(service, method, args)


    # Helper method for direct execution (no cache)
    async def _call_direct(self, service: str, method: str, args: list) -> Any:
         """
         Directly execute the JSON-RPC call to Odoo without using any cache.

         Uses `asyncio.to_thread` to run the synchronous `requests.post` call
         in a separate thread to avoid blocking the event loop.

         Args:
             service: The target service name.
             method: The method name.
             args: List of arguments for the method.

         Returns:
             The result from the Odoo method.

         Raises:
             AuthError: If Odoo returns an authentication/access error.
             ProtocolError: If the response is invalid JSON or a non-auth JSON-RPC error occurs.
             NetworkError: For network-level errors during the call.
             OdooMCPError: For other unexpected errors.
         """
         # Note: Authentication details might need to be added to payload_params
         # based on SessionManager/OdooAuthenticator integration. This implementation
         # currently assumes session cookies or similar handle auth via self.session.
         payload_params = {
             "service": service,
             "method": method,
             "args": [self.database, *args] # Simplified args structure
         }
         payload = self._prepare_payload("call", payload_params)
         headers = {'Content-Type': 'application/json'}
         request_timeout = self.config.get('timeout', 30)

         try:
             response = await asyncio.to_thread(
                 self.session.post, self.jsonrpc_url, headers=headers, json=payload, timeout=request_timeout
             )
             # Alternative using an async http client like httpx or aiohttp:
             # async with self.async_session.post(self.jsonrpc_url, headers=headers, json=payload, timeout=request_timeout) as response:
             #    response.raise_for_status()
             #    result = await response.json()

             response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
             result = response.json()

             if result.get("error"):
                 error_data = result["error"]
                 error_message = error_data.get('message', 'Unknown JSON-RPC Error')
                 error_debug_info = error_data.get('data', {}).get('debug', '')
                 full_error = f"{error_message} - {error_debug_info}".strip(" -")
                 # Check for specific error types (e.g., authentication)
                 if "AccessDenied" in str(error_data) or "AccessError" in str(error_data) or error_data.get('code') == 100: # Odoo specific code?
                      raise AuthError(f"JSON-RPC Access Denied/Error: {full_error}", original_exception=Exception(str(error_data)))
                 else:
                      raise ProtocolError(f"JSON-RPC Error Response: {full_error}", original_exception=Exception(str(error_data)))

             return result.get("result")

         except requests.exceptions.Timeout as e:
             raise NetworkError(f"JSON-RPC request timed out after {request_timeout} seconds", original_exception=e)
         except requests.exceptions.ConnectionError as e:
              raise NetworkError(f"JSON-RPC Connection Error: Unable to connect to {self.jsonrpc_url}", original_exception=e)
         except requests.exceptions.RequestException as e:
             raise NetworkError(f"JSON-RPC Network/HTTP Error: {e}", original_exception=e)
         except json.JSONDecodeError as e:
              raise ProtocolError("Failed to decode JSON-RPC response", original_exception=e)
         except Exception as e:
              raise OdooMCPError(f"An unexpected error occurred during JSON-RPC call: {e}", original_exception=e)


    # Helper method decorated with cachetools TTL cache (if available)
    @cache_manager.get_ttl_cache_decorator(cache_instance=cache_manager.odoo_read_cache if cache_manager and CACHE_TYPE == 'cachetools' else None)
    async def _call_cached(self, service: str, method: str, args: tuple) -> Any:
        """
        Wrapper method for cached execution using cachetools.

        This method is decorated by the TTL cache decorator. It calls the direct
        execution method `_call_direct`. The cache key is automatically
        generated by `cachetools.keys.hashkey` based on service, method, and args.

        Args:
            service: The target service name.
            method: The method name.
            args: Hashable tuple of positional arguments.

        Returns:
            The result from `_call_direct`, potentially from cache.
        """
        logger.debug(f"Executing CACHED JSON-RPC call wrapper for {service}.{method}")
        # Important: Ensure args is hashable! Convert lists inside args to tuples if necessary.
        # The _make_hashable check is done before calling this method in `call`.
        # try:
        #     hashable_args = self._make_hashable(args) # Already done in call()
        # except TypeError as e:
        #     logger.warning(f"Could not make arguments hashable for caching {service}.{method}: {e}. Executing directly.")
            # Fallback to direct execution if args cannot be hashed
            # return await self._call_direct(service, method, list(args)) # Fallback handled in call()

        # Call the direct method - the decorator handles caching the result.
        # Pass args as a list as expected by _call_direct
        return await self._call_direct(service, method, list(args))

    # Helper to make nested structures hashable for caching keys (can be shared)
    def _make_hashable(self, item: Any) -> Any:
        """Recursively convert mutable collection types (list, dict, set) into immutable, hashable types (tuple)."""
        if isinstance(item, dict):
            # Convert dict to sorted tuple of (key, hashable_value) pairs
            return tuple(sorted((k, self._make_hashable(v)) for k, v in item.items()))
        elif isinstance(item, list):
            return tuple(self._make_hashable(i) for i in item)
        elif isinstance(item, set):
            return tuple(sorted(self._make_hashable(i) for i in item))
        return item


    # --- Original call method's error handling (now in _call_direct) ---
    # def call(self, service: str, method: str, args: list) -> Any:
    #     """
    #     Makes a JSON-RPC call to Odoo.
    #     Note: Odoo's JSON-RPC endpoint structure might vary.
    #           This assumes a common pattern like /jsonrpc with service/method in params.
    #           Adjust based on actual Odoo JSON-RPC API structure.
    #     """
    #     # ... (rest of original implementation is now in _call_direct) ...
