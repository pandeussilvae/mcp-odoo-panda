"""
Custom exceptions for the Odoo MCP Server application.
"""

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

class PoolError(OdooMCPError):
    """Base exception for errors originating from the ConnectionPool."""
    pass

class PoolTimeoutError(PoolError):
    """Raised specifically when acquiring a connection from the pool times out."""
    pass

class SessionError(OdooMCPError):
    """Raised for errors related to user session management."""
    pass

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
