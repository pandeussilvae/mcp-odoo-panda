"""
FastMCP - Fast Model-Controller-Protocol implementation.
This module provides the core classes for MCP protocol implementation.
"""

from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass
from enum import Enum


class MCPMethod(str, Enum):
    """MCP method types."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


@dataclass
class MCPRequest:
    """MCP request object."""

    method: str
    resource: Optional[str] = None
    tool: Optional[str] = None
    operation: Optional[str] = None
    parameters: Dict[str, Any] = None
    headers: Dict[str, str] = None
    id: Optional[str] = None

    def __post_init__(self):
        """Initialize default values."""
        if self.parameters is None:
            self.parameters = {}
        if self.headers is None:
            self.headers = {}


@dataclass
class MCPResponse:
    """MCP response object."""

    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    headers: Dict[str, str] = None

    def __post_init__(self):
        """Initialize default values."""
        if self.headers is None:
            self.headers = {}

    @classmethod
    def success(cls, data: Any = None, headers: Dict[str, str] = None) -> "MCPResponse":
        """Create a success response."""
        return cls(success=True, data=data, headers=headers)

    @classmethod
    def error(cls, error: str, headers: Dict[str, str] = None) -> "MCPResponse":
        """Create an error response."""
        return cls(success=False, error=error, headers=headers)


class FastMCP:
    """FastMCP server implementation."""

    def __init__(self):
        """Initialize FastMCP server."""
        self.resource_handlers: Dict[str, callable] = {}
        self.tool_handlers: Dict[str, callable] = {}
        self.default_handler: Optional[callable] = None

    def register_resource_handler(self, handler: callable) -> None:
        """Register a resource handler."""
        self.resource_handlers["resource"] = handler

    def register_tool_handler(self, handler: callable) -> None:
        """Register a tool handler."""
        self.tool_handlers["tool"] = handler

    def register_default_handler(self, handler: callable) -> None:
        """Register a default handler."""
        self.default_handler = handler

    async def start(self, host: str = "localhost", port: int = 8000) -> None:
        """Start the FastMCP server."""
        # Implementation will be added when needed
        pass

    async def stop(self) -> None:
        """Stop the FastMCP server."""
        # Implementation will be added when needed
        pass


def mcp_handler(func):
    """Decorator for MCP handlers."""
    return func


def mcp_resource(func):
    """Decorator for MCP resource handlers."""
    return func


def mcp_tool(func):
    """Decorator for MCP tool handlers."""
    return func
