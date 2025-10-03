from xmlrpc.client import ServerProxy, Fault, ProtocolError as XmlRpcProtocolError
import socket
import asyncio
import logging
import re
from typing import Dict, Any, Optional, List, Union

from odoo_mcp.core.base_handler import BaseOdooHandler, safe_cache_decorator
from odoo_mcp.error_handling.exceptions import (
    AuthError,
    NetworkError,
    OdooMCPError,
    OdooValidationError,
    OdooRecordNotFoundError,
    OdooMethodNotFoundError,
    ProtocolError,
)

logger = logging.getLogger(__name__)


class XMLRPCHandler(BaseOdooHandler):
    """
    Handles communication with Odoo using the XML-RPC protocol.

    Manages ServerProxy instances for common and object endpoints and provides
    a method to execute model methods, incorporating caching for read operations.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the XMLRPCHandler.

        Creates ServerProxy instances for Odoo's common and object XML-RPC endpoints.
        Uses the base class for common functionality.

        Args:
            config: The server configuration dictionary. Requires 'odoo_url',
                    'database', 'username', 'api_key'.

        Raises:
            NetworkError: If creating the ServerProxy instances fails due to
                          connection or protocol issues.
            OdooMCPError: For other unexpected errors during initialization.
        """
        super().__init__(config)
        
        # Create ServerProxy instances
        self._create_proxies()
        
        # Note: Global authentication will be performed on first use
        # to avoid blocking initialization

    def _create_proxies(self) -> None:
        """Create ServerProxy instances for common and object endpoints."""
        common_url = f"{self.odoo_url}/xmlrpc/2/common"
        models_url = f"{self.odoo_url}/xmlrpc/2/object"
        
        try:
            self.common = ServerProxy(common_url, context=self.ssl_context, allow_none=True)
            self.models = ServerProxy(models_url, context=self.ssl_context, allow_none=True)
            logger.info("XMLRPCHandler initialized proxies for common and object endpoints.")
        except (XmlRpcProtocolError, socket.gaierror, ConnectionRefusedError, OSError) as e:
            raise NetworkError(
                f"Failed to connect via XML-RPC at {common_url}: {e}", original_exception=e
            )
        except Exception as e:
            raise OdooMCPError(f"Unexpected error during XMLRPC proxy creation: {e}", original_exception=e)

    async def _perform_authentication(self, username: str, password: str, database: str) -> Union[int, bool, None]:
        """Perform authentication using XML-RPC."""
        try:
            return self.common.authenticate(database, username, password, {})
        except Exception as e:
            logger.error(f"XML-RPC authentication failed: {e}")
            raise AuthError(f"Authentication failed: {e}")

    async def call(self, service: str, method: str, args: list) -> Any:
        """Make a direct call to a service method using XML-RPC."""
        try:
            if service == "common":
                proxy = self.common
            elif service == "object":
                proxy = self.models
            else:
                raise OdooMCPError(f"Unknown service: {service}")
            
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, getattr(proxy, method), *args)
        except Exception as e:
            logger.error(f"XML-RPC call failed for {service}.{method}: {e}")
            raise OdooMCPError(f"Call failed: {e}")

    async def cleanup(self) -> None:
        """Clean up XML-RPC connections."""
        try:
            if hasattr(self, 'common'):
                self.common.close()
            if hasattr(self, 'models'):
                self.models.close()
        except Exception as e:
            logger.warning(f"Error during XMLRPC cleanup: {e}")

    READ_METHODS = {"read", "search", "search_read", "search_count", "fields_get", "default_get"}

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
                        self.database, self.global_uid, self.global_password, model, method, args or [], kwargs or {}
                    ),
                )
                return result
            finally:
                proxy.close()
        except Fault as e:
            logger.error(f"XML-RPC Fault: {str(e)}")
            # Check if this is a method not found error
            if "does not exist on the model" in str(e) or "AttributeError" in str(e):
                match = re.search(r"The method '([^']+)' does not exist on the model '([^']+)'", str(e))
                if match:
                    method_name = match.group(1)
                    model_name = match.group(2)
                    raise OdooMethodNotFoundError(model_name, method_name, original_exception=e)
                else:
                    raise ProtocolError(f"XML-RPC Method Not Found Error: {str(e)}", original_exception=e)
            # Check if this is a validation error (UserError, ValidationError, aggregation error)
            elif "UserError" in str(e) or "ValidationError" in str(e) or "Funzione di aggregazione" in str(e):
                if "Funzione di aggregazione" in str(e):
                    raise OdooValidationError(f"XML-RPC Aggregation Error: {str(e)}", original_exception=e)
                else:
                    raise OdooValidationError(f"XML-RPC Validation Error: {str(e)}", original_exception=e)
            else:
                raise ProtocolError(f"XML-RPC Fault: {str(e)}", original_exception=e)
        except Exception as e:
            logger.error(f"Error executing XML-RPC method: {str(e)}")
            raise NetworkError(f"Error executing XML-RPC method: {str(e)}", original_exception=e)
