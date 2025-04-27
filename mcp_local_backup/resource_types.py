"""
MCP (Model Context Protocol) type definitions.
These types define the core data structures used in the MCP protocol.
"""

from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass
from enum import Enum
from abc import ABC, abstractmethod

class ResourceType(Enum):
    """Types of resources that can be managed by the server."""
    RECORD = "record"
    LIST = "list"
    BINARY = "binary"

@dataclass
class Resource:
    """Represents a resource in the MCP protocol."""
    uri: str
    type: ResourceType
    data: Any
    mime_type: str = "application/json"

@dataclass
class ResourceTemplate:
    """Template for creating new resources."""
    uri_template: str
    name: str
    description: str
    mime_type: str = "application/json"

@dataclass
class Tool:
    """Represents a tool that can be used to manipulate resources."""
    name: str
    description: str
    input_schema: Dict[str, Any]

@dataclass
class Prompt:
    """Represents an interactive prompt for user guidance."""
    name: str
    description: str
    arguments: List[Dict[str, Any]]

@dataclass
class ServerInfo:
    """
    Information about the MCP server.
    Use from_dict to safely construct from dicts with extra keys.
    """
    name: str
    version: str
    capabilities: Dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict):
        allowed = {"name", "version", "capabilities"}
        filtered = {k: v for k, v in data.items() if k in allowed}
        return cls(**filtered)

@dataclass
class ClientInfo:
    """
    Information about the MCP client.
    Use from_dict to safely construct from dicts with extra keys.
    """
    name: str
    version: str
    capabilities: Dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict):
        allowed = {"name", "version", "capabilities"}
        filtered = {k: v for k, v in data.items() if k in allowed}
        return cls(**filtered)

@dataclass
class GetPromptResult:
    """Result of a prompt operation."""
    prompt: Prompt
    message: str
    data: Optional[Dict[str, Any]] = None

@dataclass
class PromptMessage:
    """Message from a prompt to the user."""
    content: str
    type: str = "text"

@dataclass
class TextContent:
    """Text content for a prompt message."""
    text: str
    format: str = "plain"

class Server(ABC):
    """Base class for MCP servers."""
    @abstractmethod
    async def initialize(self, client_info: ClientInfo) -> ServerInfo:
        """Initialize the server with client information."""
        pass

    @abstractmethod
    async def get_resource(self, uri: str) -> Resource:
        """Get a resource by URI."""
        pass

    @abstractmethod
    async def list_resources(self, template: Optional[ResourceTemplate] = None) -> List[Resource]:
        """List available resources."""
        pass

    @abstractmethod
    async def list_tools(self) -> List[Tool]:
        """List available tools."""
        pass

    @abstractmethod
    async def list_prompts(self) -> List[Prompt]:
        """List available prompts."""
        pass

    @abstractmethod
    async def get_prompt(self, name: str, args: Dict[str, Any]) -> GetPromptResult:
        """Get a prompt by name."""
        pass 