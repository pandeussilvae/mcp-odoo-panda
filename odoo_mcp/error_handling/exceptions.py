"""
Custom exceptions for Odoo MCP Server.
This module provides custom exception classes for error handling.
"""

class OdooMCPError(Exception):
    """Base exception class for Odoo MCP errors."""
    def __init__(self, message: str, code: int = -32000):
        self.message = message
        self.code = code
        super().__init__(self.message)

    def to_jsonrpc_error(self) -> dict:
        """Convert exception to JSON-RPC error object."""
        return {
            'code': self.code,
            'message': self.message,
            'data': {
                'exception': self.__class__.__name__,
                'args': self.args
            }
        }

class AuthError(OdooMCPError):
    """Authentication error."""
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, code=-32001)

class NetworkError(OdooMCPError):
    """Network error."""
    def __init__(self, message: str = "Network error occurred"):
        super().__init__(message, code=-32002)

class ProtocolError(OdooMCPError):
    """Protocol error."""
    def __init__(self, message: str = "Protocol error occurred"):
        super().__init__(message, code=-32003)

class ConfigurationError(OdooMCPError):
    """Configuration error."""
    def __init__(self, message: str = "Configuration error occurred"):
        super().__init__(message, code=-32004)

class ConnectionError(OdooMCPError):
    """Connection error."""
    def __init__(self, message: str = "Connection error occurred"):
        super().__init__(message, code=-32005)

class SessionError(OdooMCPError):
    """Session error."""
    def __init__(self, message: str = "Session error occurred"):
        super().__init__(message, code=-32006)

class OdooValidationError(OdooMCPError):
    """Odoo validation error."""
    def __init__(self, message: str = "Validation error occurred"):
        super().__init__(message, code=-32007)

class OdooRecordNotFoundError(OdooMCPError):
    """Odoo record not found error."""
    def __init__(self, message: str = "Record not found"):
        super().__init__(message, code=-32008)

class PoolTimeoutError(OdooMCPError):
    """Connection pool timeout error."""
    def __init__(self, message: str = "Connection pool timeout"):
        super().__init__(message, code=-32009)

class RateLimitError(OdooMCPError):
    """Rate limit error."""
    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message, code=-32010)

class ResourceError(OdooMCPError):
    """Resource error."""
    def __init__(self, message: str = "Resource error occurred"):
        super().__init__(message, code=-32011)

class ToolError(OdooMCPError):
    """Tool error."""
    def __init__(self, message: str = "Tool error occurred"):
        super().__init__(message, code=-32012)

class PromptError(OdooMCPError):
    """Prompt error."""
    def __init__(self, message: str = "Prompt error occurred"):
        super().__init__(message, code=-32013)

class CacheError(OdooMCPError):
    """Cache error."""
    def __init__(self, message: str = "Cache error occurred"):
        super().__init__(message, code=-32014)

class BusError(OdooMCPError):
    """Bus error."""
    def __init__(self, message: str = "Bus error occurred"):
        super().__init__(message, code=-32015)
