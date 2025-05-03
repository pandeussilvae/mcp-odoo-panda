"""
Custom exceptions for Odoo MCP Server.
This module provides custom exception classes for error handling.
"""

from typing import Optional

class OdooMCPError(Exception):
    """Base exception class for Odoo MCP errors."""
    def __init__(self, message: str, code: int = -32000, original_exception: Optional[Exception] = None):
        self.message = message
        self.code = code
        self.original_exception = original_exception
        super().__init__(self.message)

    def to_jsonrpc_error(self) -> dict:
        """Convert exception to JSON-RPC error object."""
        error_data = {
            'exception': self.__class__.__name__,
            'args': self.args
        }
        if self.original_exception:
            error_data['original_exception'] = str(self.original_exception)
        return {
            'code': self.code,
            'message': self.message,
            'data': error_data
        }

class AuthError(OdooMCPError):
    """Authentication error."""
    def __init__(self, message: str = "Authentication failed", original_exception: Optional[Exception] = None):
        super().__init__(message, code=-32001, original_exception=original_exception)

class NetworkError(OdooMCPError):
    """Network error."""
    def __init__(self, message: str = "Network error occurred", original_exception: Optional[Exception] = None):
        super().__init__(message, code=-32002, original_exception=original_exception)

class ProtocolError(OdooMCPError):
    """Protocol error."""
    def __init__(self, message: str = "Protocol error occurred", original_exception: Optional[Exception] = None):
        super().__init__(message, code=-32003, original_exception=original_exception)

class ConfigurationError(OdooMCPError):
    """Configuration error."""
    def __init__(self, message: str = "Configuration error occurred", original_exception: Optional[Exception] = None):
        super().__init__(message, code=-32004, original_exception=original_exception)

class ConnectionError(OdooMCPError):
    """Connection error."""
    def __init__(self, message: str = "Connection error occurred", original_exception: Optional[Exception] = None):
        super().__init__(message, code=-32005, original_exception=original_exception)

class SessionError(OdooMCPError):
    """Session error."""
    def __init__(self, message: str = "Session error occurred", original_exception: Optional[Exception] = None):
        super().__init__(message, code=-32006, original_exception=original_exception)

class OdooValidationError(OdooMCPError):
    """Odoo validation error."""
    def __init__(self, message: str = "Validation error occurred", original_exception: Optional[Exception] = None):
        super().__init__(message, code=-32007, original_exception=original_exception)

class OdooRecordNotFoundError(OdooMCPError):
    """Odoo record not found error."""
    def __init__(self, message: str = "Record not found", original_exception: Optional[Exception] = None):
        super().__init__(message, code=-32008, original_exception=original_exception)

class PoolTimeoutError(OdooMCPError):
    """Connection pool timeout error."""
    def __init__(self, message: str = "Connection pool timeout", original_exception: Optional[Exception] = None):
        super().__init__(message, code=-32009, original_exception=original_exception)

class RateLimitError(OdooMCPError):
    """Rate limit error."""
    def __init__(self, message: str = "Rate limit exceeded", original_exception: Optional[Exception] = None):
        super().__init__(message, code=-32010, original_exception=original_exception)

class ResourceError(OdooMCPError):
    """Resource error."""
    def __init__(self, message: str = "Resource error occurred", original_exception: Optional[Exception] = None):
        super().__init__(message, code=-32011, original_exception=original_exception)

class ToolError(OdooMCPError):
    """Tool error."""
    def __init__(self, message: str = "Tool error occurred", original_exception: Optional[Exception] = None):
        super().__init__(message, code=-32012, original_exception=original_exception)

class PromptError(OdooMCPError):
    """Prompt error."""
    def __init__(self, message: str = "Prompt error occurred", original_exception: Optional[Exception] = None):
        super().__init__(message, code=-32013, original_exception=original_exception)

class CacheError(OdooMCPError):
    """Cache error."""
    def __init__(self, message: str = "Cache error occurred", original_exception: Optional[Exception] = None):
        super().__init__(message, code=-32014, original_exception=original_exception)

class BusError(OdooMCPError):
    """Bus error."""
    def __init__(self, message: str = "Bus error occurred", original_exception: Optional[Exception] = None):
        super().__init__(message, code=-32015, original_exception=original_exception)
