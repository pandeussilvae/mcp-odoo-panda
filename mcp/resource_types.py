"""
MCP (Model Context Protocol) type definitions.
These types define the core data structures used in the MCP protocol.
"""

from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass
from enum import Enum

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
    """Information about the MCP server."""
    name: str
    version: str
    capabilities: Dict[str, Any]

@dataclass
class ClientInfo:
    """Information about the MCP client."""
    name: str
    version: str
    capabilities: Dict[str, Any]

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