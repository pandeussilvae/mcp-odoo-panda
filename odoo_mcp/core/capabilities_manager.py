"""
MCP Capabilities Manager implementation.
This module provides centralized capabilities management for the MCP server.
"""

import logging
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class ResourceTemplate:
    """Resource template definition."""
    uri_template: str
    name: str
    description: str
    type: str
    mime_type: str

@dataclass
class Tool:
    """Tool definition."""
    name: str
    description: str
    parameters: Dict[str, Any]
    returns: Dict[str, Any]

@dataclass
class Prompt:
    """Prompt definition."""
    name: str
    description: str
    parameters: Dict[str, Any]
    returns: Dict[str, Any]

class CapabilitiesManager:
    """
    Manages server capabilities and feature flags.
    Provides centralized access to server capabilities and handles capability updates.
    """

    def __init__(self):
        """Initialize the capabilities manager."""
        self._resource_templates: List[ResourceTemplate] = []
        self._tools: List[Tool] = []
        self._prompts: List[Prompt] = []
        self._feature_flags: Set[str] = {
            "prompts.listChanged",
            "resources.subscribelistChanged",
            "tools.listChanged",
            "logging",
            "completion"
        }
        self._experimental_features: Dict[str, Any] = {}

    def add_resource_template(self, template: ResourceTemplate) -> None:
        """
        Add a resource template.

        Args:
            template: The resource template to add
        """
        self._resource_templates.append(template)
        self._notify_capability_change("resources.subscribelistChanged")

    def add_tool(self, tool: Tool) -> None:
        """
        Add a tool.

        Args:
            tool: The tool to add
        """
        self._tools.append(tool)
        self._notify_capability_change("tools.listChanged")

    def add_prompt(self, prompt: Prompt) -> None:
        """
        Add a prompt.

        Args:
            prompt: The prompt to add
        """
        self._prompts.append(prompt)
        self._notify_capability_change("prompts.listChanged")

    def enable_feature_flag(self, flag: str) -> None:
        """
        Enable a feature flag.

        Args:
            flag: The feature flag to enable
        """
        self._feature_flags.add(flag)
        self._notify_capability_change(flag)

    def disable_feature_flag(self, flag: str) -> None:
        """
        Disable a feature flag.

        Args:
            flag: The feature flag to disable
        """
        self._feature_flags.discard(flag)
        self._notify_capability_change(flag)

    def add_experimental_feature(self, name: str, feature: Any) -> None:
        """
        Add an experimental feature.

        Args:
            name: The name of the experimental feature
            feature: The feature definition
        """
        self._experimental_features[name] = feature

    def get_capabilities(self) -> Dict[str, Any]:
        """
        Get the current server capabilities.

        Returns:
            Dict[str, Any]: The current capabilities
        """
        return {
            "resources": {
                "listChanged": "resources.subscribelistChanged" in self._feature_flags,
                "resources": {
                    template.uri_template: {
                        "name": template.name,
                        "description": template.description,
                        "type": template.type,
                        "mimeType": template.mime_type
                    }
                    for template in self._resource_templates
                },
                "subscribe": "resources.subscribelistChanged" in self._feature_flags
            },
            "tools": {
                "listChanged": "tools.listChanged" in self._feature_flags,
                "tools": {
                    tool.name: {
                        "description": tool.description,
                        "parameters": tool.parameters,
                        "returns": tool.returns
                    }
                    for tool in self._tools
                }
            },
            "prompts": {
                "listChanged": "prompts.listChanged" in self._feature_flags,
                "prompts": {
                    prompt.name: {
                        "description": prompt.description,
                        "parameters": prompt.parameters,
                        "returns": prompt.returns
                    }
                    for prompt in self._prompts
                }
            },
            "experimental": self._experimental_features
        }

    def _notify_capability_change(self, flag: str) -> None:
        """
        Notify about a capability change.

        Args:
            flag: The feature flag that changed
        """
        logger.info(f"Capability change: {flag}")
        # TODO: Implement notification mechanism for capability changes 