"""
Custom exceptions for the Odoo MCP Server application.
"""
from typing import Dict, Any

class OdooMCPError(Exception):
    """Base exception for all custom errors raised by the Odoo MCP Server application."""

    def __init__(self, message: str, original_exception: Exception = None):
        """
        Initialize the base MCP error.

        Args:
            message: The error message describing the issue.
            original_exception: The original exception that caused this error, if any.
        """
        super().__init__(message)
        self.original_exception = original_exception
        self.message = message

    def __str__(self):
        if self.original_exception:
            return f"{self.message}: {self.original_exception}"
        return self.message

class AuthError(OdooMCPError):
    """Raised when an authentication attempt fails or access is denied by Odoo."""
    pass

class NetworkError(OdooMCPError):
    """Raised for network-related issues during communication with Odoo.

    This includes timeouts, DNS resolution failures, connection refusals, etc.
    """
    pass

class ProtocolError(OdooMCPError):
    """Raised for errors related to the communication protocol (XML-RPC, JSON-RPC).

    This includes issues like malformed requests/responses, unexpected data formats,
    or specific protocol faults reported by the server (e.g., XML-RPC Faults not related to auth).
    """
    pass

class ConfigurationError(OdooMCPError):
    """Raised when errors are detected in the server's configuration."""
    pass

class ConnectionError(OdooMCPError):
    """Base exception for errors related to connection management (e.g., pool errors, connection failures)."""
    pass

class PoolTimeoutError(ConnectionError): # Inherit from ConnectionError now
    """Raised specifically when acquiring a connection from the pool times out."""
    pass

class SessionError(OdooMCPError):
    """Raised for errors related to user session management."""
    pass

class OdooValidationError(ProtocolError): # Inherit from ProtocolError as it's an execution error
    """Raised specifically for Odoo model validation failures (e.g., UserError)."""
    default_code = -32010 # Example custom code for Odoo validation
    default_message = "Odoo validation error"

    def to_jsonrpc_error(self) -> Dict[str, Any]:
        """Convert exception to JSON-RPC error object using specific code."""
        return {
            "code": self.default_code,
            "message": self.message or self.default_message,
            "data": str(self.original_exception) if self.original_exception else None
        }

class OdooRecordNotFoundError(ProtocolError): # Inherit from ProtocolError
    """Raised when an operation targets a record that does not exist."""
    default_code = -32011 # Example custom code for Odoo record not found
    default_message = "Odoo record not found"

    def to_jsonrpc_error(self) -> Dict[str, Any]:
        """Convert exception to JSON-RPC error object using specific code."""
        return {
            "code": self.default_code,
            "message": self.message or self.default_message,
            "data": str(self.original_exception) if self.original_exception else None
        }

# Example of how to use them:
#
# try:
#     # some operation
#     pass
# except xmlrpc.client.Fault as e:
#     raise ProtocolError(f"XML-RPC Fault: {e.faultString}", original_exception=e)
# except requests.exceptions.Timeout as e:
#     raise NetworkError("Request timed out", original_exception=e)
# except KeyError as e:
#     raise ConfigurationError(f"Missing configuration key: {e}", original_exception=e)
# except Exception as e:
#     # Generic fallback or re-raise as OdooMCPError
#     raise OdooMCPError("An unexpected error occurred", original_exception=e)
