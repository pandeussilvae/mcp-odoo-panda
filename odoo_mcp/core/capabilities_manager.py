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
        # Register resource templates
        self.register_resource(ResourceTemplate(
            name="res.partner",
            type=ResourceType.MODEL,
            description="Odoo Partner/Contact resource",
            operations=["create", "read", "update", "delete", "search"],
            parameters={
                "uri_template": "odoo://{model}/{id}",
                "list_uri_template": "odoo://{model}/list",
                "binary_uri_template": "odoo://{model}/binary/{field}/{id}"
            }
        ))
        
        self.register_resource(ResourceTemplate(
            name="res.users",
            type=ResourceType.MODEL,
            description="Odoo User resource",
            operations=["create", "read", "update", "delete", "search"],
            parameters={
                "uri_template": "odoo://{model}/{id}",
                "list_uri_template": "odoo://{model}/list",
                "binary_uri_template": "odoo://{model}/binary/{field}/{id}"
            }
        ))

        self.register_resource(ResourceTemplate(
            name="product.product",
            type=ResourceType.MODEL,
            description="Odoo Product resource",
            operations=["create", "read", "update", "delete", "search"],
            parameters={
                "uri_template": "odoo://{model}/{id}",
                "list_uri_template": "odoo://{model}/list",
                "binary_uri_template": "odoo://{model}/binary/{field}/{id}"
            }
        ))

        self.register_resource(ResourceTemplate(
            name="sale.order",
            type=ResourceType.MODEL,
            description="Odoo Sales Order resource",
            operations=["create", "read", "update", "delete", "search"],
            parameters={
                "uri_template": "odoo://{model}/{id}",
                "list_uri_template": "odoo://{model}/list",
                "binary_uri_template": "odoo://{model}/binary/{field}/{id}"
            }
        ))

        self.register_resource(ResourceTemplate(
            name="ir.attachment",
            type=ResourceType.BINARY,
            description="Odoo Attachment resource",
            operations=["create", "read", "update", "delete"],
            parameters={
                "uri_template": "odoo://{model}/{id}",
                "binary_uri_template": "odoo://{model}/binary/{field}/{id}"
            }
        ))
        
        # Register tools
        self.register_tool(Tool(
            name="odoo_execute_kw",
            description="Execute an arbitrary method on an Odoo model",
            operations=["execute"],
            parameters={
                "model": "string",
                "method": "string",
                "args": "array",
                "kwargs": "object"
            }
        ))

        self.register_tool(Tool(
            name="data_export",
            description="Export Odoo data to various formats",
            operations=["csv", "excel", "json", "xml"],
            parameters={
                "model": "string",
                "ids": "array",
                "fields": "array",
                "format": "string"
            }
        ))
        
        self.register_tool(Tool(
            name="data_import",
            description="Import data into Odoo",
            operations=["csv", "excel", "json", "xml"],
            parameters={
                "model": "string",
                "data": "string",
                "format": "string"
            }
        ))

        self.register_tool(Tool(
            name="report_generator",
            description="Generate an Odoo report",
            operations=["pdf", "html"],
            parameters={
                "report_name": "string",
                "ids": "array",
                "format": "string"
            }
        ))

        self.register_tool(Tool(
            name="odoo_create_record",
            description="Create a new record in an Odoo model",
            operations=["create"],
            parameters={
                "model": "string",
                "values": "object"
            }
        ))

        self.register_tool(Tool(
            name="odoo_update_record",
            description="Update an existing record in an Odoo model",
            operations=["write"],
            parameters={
                "model": "string",
                "id": "integer",
                "values": "object"
            }
        ))

        self.register_tool(Tool(
            name="odoo_delete_record",
            description="Delete a record from an Odoo model",
            operations=["unlink"],
            parameters={
                "model": "string",
                "id": "integer"
            }
        ))

        self.register_tool(Tool(
            name="odoo_search_records",
            description="Search records in an Odoo model",
            operations=["search_read"],
            parameters={
                "model": "string",
                "domain": "array",
                "fields": "array",
                "limit": "integer"
            }
        ))
        
        # Register prompts
        self.register_prompt(Prompt(
            name="analyze_record",
            description="Analyze an Odoo record",
            template="Analyze the following Odoo record: {record}",
            parameters={
                "model": "string",
                "id": "integer"
            }
        ))
        
        self.register_prompt(Prompt(
            name="create_record",
            description="Create a new Odoo record",
            template="Create a new {model} record with the following data: {data}",
            parameters={
                "model": "string"
            }
        ))

        self.register_prompt(Prompt(
            name="update_record",
            description="Update an existing Odoo record",
            template="Update the {model} record with ID {id} with the following data: {data}",
            parameters={
                "model": "string",
                "id": "integer"
            }
        ))

        self.register_prompt(Prompt(
            name="advanced_search",
            description="Perform an advanced search on an Odoo model",
            template="Search {model} records with the following criteria: {criteria}",
            parameters={
                "model": "string"
            }
        ))

        self.register_prompt(Prompt(
            name="call_method",
            description="Call a specific method on a model or record",
            template="Call method {method} on {model} with ID {id} and arguments: {args}",
            parameters={
                "model": "string",
                "method": "string",
                "id": "integer",
                "args": "array",
                "kwargs": "object"
            }
        ))

        self.register_prompt(Prompt(
            name="view_related_records",
            description="View records related to a specific record",
            template="Show records related to {model} with ID {id} through field {field}",
            parameters={
                "model": "string",
                "id": "integer",
                "field": "string"
            }
        ))

        self.register_prompt(Prompt(
            name="upload_attachment",
            description="Upload a file attachment to a record",
            template="Upload file {filename} to {model} with ID {id}",
            parameters={
                "model": "string",
                "id": "integer",
                "filename": "string"
            }
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

    def list_resources(self) -> List[Dict[str, Any]]:
        """
        List all registered resources.

        Returns:
            List[Dict[str, Any]]: List of resource templates as dictionaries with the following structure:
            {
                "name": str,
                "type": str,
                "description": str,
                "operations": List[str],
                "parameters": Optional[Dict[str, Any]],
                "uri": str  # Required field for MCP client
            }
        """
        return [
            {
                "name": resource.name,
                "type": resource.type.value,
                "description": resource.description,
                "operations": resource.operations,
                "parameters": resource.parameters or {},
                "uri": f"odoo://{resource.name}"  # Add URI field in odoo:// format
            }
            for resource in self.resources.values()
        ]

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
        Get server capabilities following MCP 2025-03-26 specification.

        Returns:
            Dict[str, Any]: Server capabilities with the following structure:
            {
                "logging": {},
                "prompts": {
                    "listChanged": true
                },
                "resources": {
                    "subscribe": true,
                    "listChanged": true
                },
                "tools": {
                    "listChanged": true
                }
            }
        """
        return {
            "logging": {},  # Empty object indicates basic logging support
            "prompts": {
                "listChanged": self.is_feature_enabled('prompts.listChanged')
            },
            "resources": {
                "subscribe": self.is_feature_enabled('resources.subscribe'),
                "listChanged": self.is_feature_enabled('resources.listChanged')
            },
            "tools": {
                "listChanged": self.is_feature_enabled('tools.listChanged')
            }
        } 