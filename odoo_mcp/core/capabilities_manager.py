"""
Capabilities Manager implementation for Odoo MCP Server.
This module provides capability management and feature flag handling.
"""

import logging
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class ResourceType(str, Enum):
    """Resource types supported by the server."""
    MODEL = "model"
    BINARY = "binary"
    LIST = "list"
    RECORD = "record"

@dataclass
class ResourceTemplate:
    """Resource template definition."""
    name: str
    type: ResourceType
    description: str
    operations: List[str]
    parameters: Optional[Dict[str, Any]] = None

@dataclass
class Tool:
    """Tool definition."""
    name: str
    description: str
    operations: List[str]
    parameters: Optional[Dict[str, Any]] = None

@dataclass
class Prompt:
    """Prompt definition."""
    name: str
    description: str
    template: str
    parameters: Optional[Dict[str, Any]] = None

class CapabilitiesManager:
    """Manages server capabilities and feature flags."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize capabilities manager.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.resources: Dict[str, ResourceTemplate] = {}
        self.tools: Dict[str, Tool] = {}
        self.prompts: Dict[str, Prompt] = {}
        self.feature_flags: Dict[str, bool] = {
            'prompts.listChanged': True,
            'resources.subscribelistChanged': True,
            'tools.listChanged': True,
            'logging': True,
            'completion': True
        }
        
        # Register default capabilities
        self._register_default_capabilities()

    def _register_default_capabilities(self) -> None:
        """Register default server capabilities."""
        # Register default resources
        self.register_resource(ResourceTemplate(
            name="res.partner",
            type=ResourceType.MODEL,
            description="Odoo Partner/Contact resource",
            operations=["create", "read", "update", "delete", "search"]
        ))
        
        self.register_resource(ResourceTemplate(
            name="res.users",
            type=ResourceType.MODEL,
            description="Odoo User resource",
            operations=["create", "read", "update", "delete", "search"]
        ))
        
        # Register default tools
        self.register_tool(Tool(
            name="data_export",
            description="Export Odoo data to various formats",
            operations=["csv", "excel", "json", "xml"]
        ))
        
        self.register_tool(Tool(
            name="data_import",
            description="Import data into Odoo",
            operations=["csv", "excel", "json", "xml"]
        ))
        
        # Register default prompts
        self.register_prompt(Prompt(
            name="analyze_record",
            description="Analyze an Odoo record",
            template="Analyze the following Odoo record: {record}"
        ))
        
        self.register_prompt(Prompt(
            name="create_record",
            description="Create a new Odoo record",
            template="Create a new {model} record with the following data: {data}"
        ))

    def register_resource(self, resource: ResourceTemplate) -> None:
        """
        Register a resource template.

        Args:
            resource: Resource template to register
        """
        self.resources[resource.name] = resource
        logger.info(f"Registered resource: {resource.name}")

    def register_tool(self, tool: Tool) -> None:
        """
        Register a tool.

        Args:
            tool: Tool to register
        """
        self.tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def register_prompt(self, prompt: Prompt) -> None:
        """
        Register a prompt.

        Args:
            prompt: Prompt to register
        """
        self.prompts[prompt.name] = prompt
        logger.info(f"Registered prompt: {prompt.name}")

    def get_resource(self, name: str) -> Optional[ResourceTemplate]:
        """
        Get a resource template by name.

        Args:
            name: Name of the resource

        Returns:
            Optional[ResourceTemplate]: Resource template if found, None otherwise
        """
        return self.resources.get(name)

    def get_tool(self, name: str) -> Optional[Tool]:
        """
        Get a tool by name.

        Args:
            name: Name of the tool

        Returns:
            Optional[Tool]: Tool if found, None otherwise
        """
        return self.tools.get(name)

    def get_prompt(self, name: str) -> Optional[Prompt]:
        """
        Get a prompt by name.

        Args:
            name: Name of the prompt

        Returns:
            Optional[Prompt]: Prompt if found, None otherwise
        """
        return self.prompts.get(name)

    def list_resources(self) -> List[str]:
        """
        List all registered resources.

        Returns:
            List[str]: List of resource names
        """
        return list(self.resources.keys())

    def list_tools(self) -> List[str]:
        """
        List all registered tools.

        Returns:
            List[str]: List of tool names
        """
        return list(self.tools.keys())

    def list_prompts(self) -> List[str]:
        """
        List all registered prompts.

        Returns:
            List[str]: List of prompt names
        """
        return list(self.prompts.keys())

    def is_feature_enabled(self, feature: str) -> bool:
        """
        Check if a feature is enabled.

        Args:
            feature: Feature name

        Returns:
            bool: True if feature is enabled, False otherwise
        """
        return self.feature_flags.get(feature, False)

    def enable_feature(self, feature: str) -> None:
        """
        Enable a feature.

        Args:
            feature: Feature name
        """
        self.feature_flags[feature] = True
        logger.info(f"Enabled feature: {feature}")

    def disable_feature(self, feature: str) -> None:
        """
        Disable a feature.

        Args:
            feature: Feature name
        """
        self.feature_flags[feature] = False
        logger.info(f"Disabled feature: {feature}")

    def get_capabilities(self) -> Dict[str, Any]:
        """
        Get server capabilities.

        Returns:
            Dict[str, Any]: Server capabilities
        """
        return {
            'resources': {
                name: {
                    'type': resource.type.value,
                    'description': resource.description,
                    'operations': resource.operations,
                    'parameters': resource.parameters
                }
                for name, resource in self.resources.items()
            },
            'tools': {
                name: {
                    'description': tool.description,
                    'operations': tool.operations,
                    'parameters': tool.parameters
                }
                for name, tool in self.tools.items()
            },
            'prompts': {
                name: {
                    'description': prompt.description,
                    'template': prompt.template,
                    'parameters': prompt.parameters
                }
                for name, prompt in self.prompts.items()
            },
            'features': self.feature_flags
        } 