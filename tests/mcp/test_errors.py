import pytest
from mcp_local_backup.errors import (
    MCPError,
    AuthError,
    RateLimitError,
    SessionError,
    ResourceError,
    ValidationError,
    ConnectionError
)

def test_mcp_error():
    error = MCPError("Test error")
    assert str(error) == "Test error"
    assert isinstance(error, Exception)

def test_auth_error():
    error = AuthError("Authentication failed")
    assert str(error) == "Authentication failed"
    assert isinstance(error, MCPError)

def test_rate_limit_error():
    error = RateLimitError("Rate limit exceeded")
    assert str(error) == "Rate limit exceeded"
    assert isinstance(error, MCPError)

def test_session_error():
    error = SessionError("Session expired")
    assert str(error) == "Session expired"
    assert isinstance(error, MCPError)

def test_resource_error():
    error = ResourceError("Resource not found")
    assert str(error) == "Resource not found"
    assert isinstance(error, MCPError)

def test_validation_error():
    error = ValidationError("Invalid input")
    assert str(error) == "Invalid input"
    assert isinstance(error, MCPError)

def test_connection_error():
    error = ConnectionError("Connection failed")
    assert str(error) == "Connection failed"
    assert isinstance(error, MCPError)

def test_error_with_details():
    error = MCPError("Test error", details={"code": 500, "message": "Internal error"})
    assert str(error) == "Test error"
    assert error.details == {"code": 500, "message": "Internal error"}

def test_error_inheritance():
    # Test that all error types inherit from MCPError
    error_types = [
        AuthError,
        RateLimitError,
        SessionError,
        ResourceError,
        ValidationError,
        ConnectionError
    ]
    
    for error_type in error_types:
        error = error_type("Test")
        assert isinstance(error, MCPError)
        assert isinstance(error, Exception) 