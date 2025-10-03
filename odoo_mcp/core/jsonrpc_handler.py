import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Union

import httpx

from odoo_mcp.core.base_handler import BaseOdooHandler, safe_cache_decorator
from odoo_mcp.error_handling.exceptions import (
    AuthError,
    ConfigurationError,
    NetworkError,
    OdooMCPError,
    OdooMethodNotFoundError,
    OdooRecordNotFoundError,
    OdooValidationError,
    ProtocolError,
)
from odoo_mcp.performance.caching import get_cache_manager, CACHE_TYPE

logger = logging.getLogger(__name__)


class JSONRPCHandler(BaseOdooHandler):
    """
    Handles communication with Odoo using the JSON-RPC protocol via HTTPX.

    Manages an asynchronous HTTP client session using `httpx.AsyncClient` and
    provides a method to execute RPC calls, incorporating caching for read operations.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the JSONRPCHandler.

        Sets up the base URL and an `httpx.AsyncClient` for making async HTTP calls.
        Uses the base class for common functionality.

        Args:
            config: The server configuration dictionary. Requires 'odoo_url', 'database'.
                    Optional TLS keys: 'tls_version', 'ca_cert_path',
                    'client_cert_path', 'client_key_path'.

        Raises:
            ConfigurationError: If TLS configuration fails.
        """
        # Handle environment variables for URL and database
        config = config.copy()
        config["odoo_url"] = os.getenv("ODOO_URL") or config.get("odoo_url")
        config["database"] = os.getenv("ODOO_DB") or config.get("database")
        config["username"] = os.getenv("ODOO_USERNAME") or config.get("username")
        config["api_key"] = os.getenv("ODOO_PASSWORD") or config.get("api_key")
        
        super().__init__(config)
        
        # Ensure URL has correct protocol
        if not self.odoo_url.startswith(("http://", "https://")):
            self.odoo_url = f"https://{self.odoo_url}"
        
        self.jsonrpc_url = f"{self.odoo_url}/jsonrpc"
        
        # Create HTTP client
        self._create_http_client()
        
        # Initialize authentication
        self.uid = None

    def _create_http_client(self) -> None:
        """Create and configure the HTTPX client."""
        # Configure TLS settings
        verify: Union[str, bool] = True
        cert: Optional[Union[str, tuple]] = None
        
        # Use SSL context from base class if available
        if self.ssl_context:
            verify = self.ssl_context
        elif self.odoo_url.startswith("https://"):
            # Configure custom certificates if provided
            ca_cert_path = self.config.get("ca_cert_path")
            if ca_cert_path:
                verify = ca_cert_path

            client_cert_path = self.config.get("client_cert_path")
            client_key_path = self.config.get("client_key_path")
            if client_cert_path and client_key_path:
                cert = (client_cert_path, client_key_path)
            elif client_cert_path:
                cert = client_cert_path

        # Create the AsyncClient
        request_timeout = int(os.getenv("TIMEOUT", self.config.get("timeout", 30)))
        self.async_client = httpx.AsyncClient(verify=verify, cert=cert, timeout=request_timeout)
        logger.info(f"httpx.AsyncClient initialized with timeout={request_timeout}s")

    async def _perform_authentication(self, username: str, password: str, database: str) -> Union[int, bool, None]:
        """Perform authentication using JSON-RPC."""
        try:
            auth_result = await self.call(
                service="common",
                method="login",
                args=[database, username, password],
            )
            return auth_result
        except Exception as e:
            logger.error(f"JSON-RPC authentication failed: {e}")
            raise AuthError(f"Authentication failed: {e}")

    async def call(self, service: str, method: str, args: list) -> Any:
        """Make a direct call to a service method using JSON-RPC."""
        try:
            # Prepare payload
            payload = self._prepare_payload(method, args)
            
            # Make HTTP request
            response = await self.async_client.post(
                self.jsonrpc_url,
                json=payload,
                headers=self._get_headers()
            )
            
            # Handle response
            if response.status_code != 200:
                raise NetworkError(f"HTTP {response.status_code}: {response.text}")
            
            result = response.json()
            
            if "error" in result:
                error = result["error"]
                raise OdooMCPError(f"JSON-RPC error: {error.get('message', 'Unknown error')}")
            
            return result.get("result")
            
        except Exception as e:
            logger.error(f"JSON-RPC call failed for {service}.{method}: {e}")
            raise OdooMCPError(f"Call failed: {e}")

    async def cleanup(self) -> None:
        """Clean up JSON-RPC connections."""
        try:
            if hasattr(self, 'async_client'):
                await self.async_client.aclose()
        except Exception as e:
            logger.warning(f"Error during JSONRPC cleanup: {e}")

    def _prepare_payload(self, method: str, params: Union[dict, list]) -> dict:
        """Prepare JSON-RPC payload."""
        return {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "object",
                "method": method,
                "args": params
            },
            "id": 1
        }

    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for requests."""
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def ensure_authenticated(self):
        """Ensure we have a valid uid by authenticating if needed."""
        if self.uid is None:
            try:
                logger.info(f"Attempting authentication with database={self.database}, username={self.username}")
                auth_result = await self.call(
                    service="common",
                    method="login",
                    args=[self.database, self.username, self.password],
                )
                if not auth_result:
                    logger.error(
                        f"Authentication failed: server returned False for database={self.database}, username={self.username}"
                    )
                    raise AuthError(f"Authentication failed: invalid credentials for database {self.database}")

                self.uid = auth_result
                logger.info(f"Successfully authenticated with uid: {self.uid}")
            except Exception as e:
                logger.error(f"Failed to authenticate: {str(e)}")
                if "Login failed" in str(e):
                    raise AuthError(f"Login failed for database {self.database} and user {self.username}")
                raise AuthError(f"Failed to authenticate: {str(e)}")
        return self.uid

    def _prepare_payload(self, method: str, params: Union[dict, list]) -> dict:
        """Prepare the standard JSON-RPC 2.0 payload structure."""
        # For Odoo's JSON-RPC interface, we need to ensure params is a list
        if isinstance(params, dict):
            # Convert dict to list of key-value pairs
            params = [params]
        elif not isinstance(params, list):
            params = [params]

        # Split the method into service and method name
        service, method_name = method.split(".")

        # For Odoo's JSON-RPC interface, we need to wrap the params in a dict
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method_name, "args": params, "kwargs": {}},
            "id": None,
        }

        return payload

    def _get_headers(self) -> Dict[str, str]:
        """Get the headers for JSON-RPC requests."""
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "OdooMCP/1.0",
        }

    READ_METHODS = {"call"}  # Assume 'call' with specific service/method might be readable

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
        is_cacheable = service == "object" and method in {
            "read",
            "search",
            "search_read",
            "search_count",
            "fields_get",
            "default_get",
        }

        if is_cacheable:
            logger.debug(f"Cacheable JSON-RPC method detected: {service}.{method}. Attempting cache lookup.")
            try:
                cache_manager = get_cache_manager()
                hashable_args = self._make_hashable(args)
            except (ConfigurationError, TypeError) as e:
                logger.warning(f"Could not use cache for {service}.{method}: {e}. Executing directly.")
                return await self._call_direct(service, method, args)

            if CACHE_TYPE == "cachetools":
                return await self._call_cached(service, method, hashable_args)
            else:
                logger.debug("Executing non-TTL cached or uncached JSON-RPC read method.")
                return await self._call_direct(service, method, args)
        else:
            logger.debug(f"Executing non-cacheable JSON-RPC method: {service}.{method}")
            return await self._call_direct(service, method, args)

    def _serialize_resource(self, resource: Any) -> Dict[str, Any]:
        """
        Convert a Resource object to a serializable dictionary.

        Args:
            resource: The resource to serialize

        Returns:
            Dict[str, Any]: A serializable dictionary representation of the resource
        """
        if hasattr(resource, "uri") and hasattr(resource, "type") and hasattr(resource, "data"):
            # Handle binary fields in data
            serialized_data = {}
            if isinstance(resource.data, dict):
                for key, value in resource.data.items():
                    if isinstance(value, bytes):
                        # Convert binary data to base64 string
                        serialized_data[key] = f"data:image/png;base64,{value.decode('utf-8')}"
                    else:
                        serialized_data[key] = value
            else:
                serialized_data = resource.data

            return {
                "uri": resource.uri,
                "type": resource.type.value if hasattr(resource.type, "value") else resource.type,
                "data": serialized_data,
                "mime_type": getattr(resource, "mime_type", "application/json"),
            }
        return resource

    async def _call_direct(self, service: str, method: str, args: list) -> Any:
        """
        Execute a direct JSON-RPC call without caching.

        Args:
            service: The service name
            method: The method name
            args: The arguments to pass

        Returns:
            Any: The result of the call
        """
        try:
            # Combine service and method for Odoo's JSON-RPC interface
            full_method = f"{service}.{method}"

            # Prepare the payload
            payload = self._prepare_payload(full_method, args)

            # Get headers
            headers = self._get_headers()

            logger.debug(f"Executing JSON-RPC (httpx): service={service}, method={method}")
            logger.debug(f"JSON-RPC Request URL: {self.jsonrpc_url}")
            logger.debug(f"JSON-RPC Request Headers: {headers}")
            logger.debug(f"JSON-RPC Request Payload: {json.dumps(payload, indent=2)}")

            response = await self.async_client.post(self.jsonrpc_url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

            logger.debug(f"JSON-RPC Response Status: {response.status_code}")
            logger.debug(f"JSON-RPC Response Headers: {dict(response.headers)}")
            try:
                logger.debug(f"JSON-RPC Response Body: {json.dumps(result, indent=2)}")
            except (TypeError, ValueError):
                logger.debug(f"JSON-RPC Response Body: {str(result)}")

            if result.get("error"):
                error_data = result["error"]
                error_message = error_data.get("message", "Unknown JSON-RPC Error")
                error_code = error_data.get("code")
                error_debug_info = error_data.get("data", {}).get("debug", "")
                full_error = f"Code {error_code}: {error_message} - {error_debug_info}".strip(" -")

                logger.error(f"JSON-RPC Error Response: {full_error}")
                try:
                    logger.error(f"JSON-RPC Error Data: {json.dumps(error_data, indent=2)}")
                except (TypeError, ValueError):
                    logger.error(f"JSON-RPC Error Data: {str(error_data)}")

                if error_code == 100 or "AccessDenied" in error_message or "AccessError" in error_message:
                    raise AuthError(
                        f"JSON-RPC Access/Auth Error: {full_error}",
                        original_exception=Exception(str(error_data)),
                    )
                elif (
                    "UserError" in error_message
                    or "ValidationError" in error_message
                    or "Funzione di aggregazione" in error_message
                ):
                    # Extract the actual error message from the data if available
                    clean_message = error_data.get("data", {}).get("message", error_message.split("\n")[0])
                    # If the message contains aggregation function error, make it more specific
                    if "Funzione di aggregazione" in clean_message:
                        raise OdooValidationError(
                            f"JSON-RPC Aggregation Error: {clean_message}",
                            original_exception=Exception(str(error_data)),
                        )
                    else:
                        raise OdooValidationError(
                            f"JSON-RPC Validation Error: {clean_message}",
                            original_exception=Exception(str(error_data)),
                        )
                elif "Record does not exist" in error_message:
                    raise OdooRecordNotFoundError(
                        f"JSON-RPC Record Not Found: {full_error}",
                        original_exception=Exception(str(error_data)),
                    )
                elif "does not exist on the model" in error_message or "AttributeError" in error_message:
                    # Extract model and method from error message
                    match = re.search(r"The method '([^']+)' does not exist on the model '([^']+)'", error_message)
                    if match:
                        method_name = match.group(1)
                        model_name = match.group(2)
                        raise OdooMethodNotFoundError(
                            model_name, method_name, original_exception=Exception(str(error_data))
                        )
                    else:
                        raise ProtocolError(
                            f"JSON-RPC Method Not Found Error: {full_error}",
                            original_exception=Exception(str(error_data)),
                        )
                else:
                    raise ProtocolError(
                        f"JSON-RPC Error Response: {full_error}",
                        original_exception=Exception(str(error_data)),
                    )

            # Return the result directly without creating a Resource object
            return result.get("result")

        except httpx.TimeoutException as e:
            logger.error(f"JSON-RPC Timeout Error: {str(e)}")
            raise NetworkError(
                f"JSON-RPC request timed out after {self.async_client.timeout.read} seconds",
                original_exception=e,
            )
        except httpx.ConnectError as e:
            logger.error(f"JSON-RPC Connection Error: {str(e)}")
            raise NetworkError(
                f"JSON-RPC Connection Error: Unable to connect to {self.jsonrpc_url}",
                original_exception=e,
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"JSON-RPC HTTP Status Error: {str(e)}")
            raise NetworkError(f"JSON-RPC HTTP {e.response.status_code}: {e.response.text}", original_exception=e)
        except httpx.RequestError as e:
            logger.error(f"JSON-RPC Request Error: {str(e)}")
            raise NetworkError(f"JSON-RPC Network/HTTP Error: {e}", original_exception=e)
        except json.JSONDecodeError as e:
            logger.error(f"JSON-RPC JSON Decode Error: {str(e)}")
            raise ProtocolError("Failed to decode JSON-RPC response", original_exception=e)
        except Exception as e:
            logger.exception(f"An unexpected error occurred during JSON-RPC call: {e}")
            raise OdooMCPError(f"An unexpected error occurred during JSON-RPC call: {e}", original_exception=e)

    @safe_cache_decorator
    async def _call_cached(self, service: str, method: str, args: tuple) -> Any:
        """
        Wrapper method for cached execution using cachetools.
        Calls the direct execution method `_call_direct`.
        """
        logger.debug(f"Executing CACHED JSON-RPC call wrapper for {service}.{method}")
        # Pass args as a list as expected by _call_direct
        return await self._call_direct(service, method, list(args))

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list,
        kwargs: dict,
        uid: Optional[int] = None,
        password: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Any:
        """
        Execute a method on an Odoo model using JSON-RPC 'object.execute_kw'.

        This method mirrors the XML-RPC execute_kw interface.

        Args:
            model: The Odoo model name.
            method: The method to call on the model.
            args: Positional arguments for the Odoo method.
            kwargs: Keyword arguments for the Odoo method. Should include 'context'.
            uid: User ID for authentication (required if password/session_id not used).
            password: Password or API key for authentication.
            session_id: Session ID to potentially include in the context.

        Returns:
            The result from the Odoo method.

        Raises:
            AuthError, NetworkError, ProtocolError, OdooMCPError, TypeError.
        """
        # Ensure we have a valid uid
        await self.ensure_authenticated()

        # Use stored credentials if not provided
        call_uid = uid if uid is not None else self.uid
        call_password = password if password is not None else self.password

        if call_uid is None or call_password is None:
            raise AuthError("No valid credentials available for JSON-RPC execute_kw")

        # Prepare context, merging session_id if provided
        context = kwargs.pop("context", {})  # Get context from kwargs or default to empty dict
        if session_id:
            context["session_id"] = session_id
            logger.debug(f"Added session_id to context for JSON-RPC call {model}.{method}")

        # Arguments for Odoo's object.execute_kw: db, uid, password, model, method, args[, kwargs]
        odoo_args = [self.database, call_uid, call_password, model, method, args]
        if kwargs or context:  # Only add kwargs dict if it's not empty
            final_kwargs = kwargs.copy()
            if context:
                final_kwargs["context"] = context
            odoo_args.append(final_kwargs)

        # Use the 'call' method to execute 'object.execute_kw'
        return await self.call(service="object", method="execute_kw", args=odoo_args)

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
            raise TypeError(
                f"Object of type {type(item).__name__} is not hashable and cannot be used in cache key"
            ) from e

    async def close(self):
        """Close the underlying httpx client session."""
        if hasattr(self, "async_client"):
            await self.async_client.aclose()
            logger.info("httpx.AsyncClient closed.")
