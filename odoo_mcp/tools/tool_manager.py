"""
Tool Manager implementation for Odoo MCP Server.
This module provides tool management and operation handling functionality.
"""

import logging
from typing import Dict, Any, Optional, List, Callable, Union
from functools import wraps

from odoo_mcp.error_handling.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

# Global tool manager instance
_tool_manager = None


def initialize_tool_manager(config: Dict[str, Any]) -> None:
    """
    Initialize the global tool manager.

    Args:
        config: Configuration dictionary

    Raises:
        ConfigurationError: If the tool manager is already initialized
    """
    global _tool_manager
    if _tool_manager is not None:
        raise ConfigurationError("Tool manager is already initialized")

    _tool_manager = ToolManager(config)
    logger.info("Tool manager initialized successfully")


def get_tool_manager() -> "ToolManager":
    """
    Get the global tool manager instance.

    Returns:
        ToolManager: The global tool manager instance

    Raises:
        ConfigurationError: If the tool manager is not initialized
    """
    if _tool_manager is None:
        raise ConfigurationError("Tool manager is not initialized")
    return _tool_manager


class ToolManager:
    """Manages Odoo tools and their operations."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the tool manager.

        Args:
            config: Configuration dictionary containing tool settings
        """
        self.config = config
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.operations: Dict[str, Dict[str, Any]] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register default Odoo tools."""
        self.register_tool(
            name="data_export",
            description="Export Odoo data to various formats",
            operations=["csv", "excel", "json", "xml"],
        )

        self.register_tool(
            name="data_import",
            description="Import data into Odoo",
            operations=["csv", "excel", "json", "xml"],
        )

        self.register_tool(
            name="report_generator",
            description="Generate Odoo reports",
            operations=["pdf", "html", "excel"],
        )

    def register_tool(self, name: str, description: str, operations: List[str]) -> None:
        """
        Register a new tool.

        Args:
            name: Name of the tool
            description: Description of the tool
            operations: List of supported operations
        """
        self.tools[name] = {"description": description, "operations": operations}
        logger.info(f"Registered tool: {name}")

    def register_operation(self, tool_name: str, operation_name: str, handler: Callable) -> None:
        """
        Register an operation handler for a tool.

        Args:
            tool_name: Name of the tool
            operation_name: Name of the operation
            handler: Operation handler function
        """
        if tool_name not in self.tools:
            raise ValueError(f"Tool not found: {tool_name}")

        if operation_name not in self.tools[tool_name]["operations"]:
            raise ValueError(f"Operation not supported for tool {tool_name}: {operation_name}")

        operation_key = f"{tool_name}.{operation_name}"
        self.operations[operation_key] = {
            "handler": handler,
            "tool": tool_name,
            "operation": operation_name,
        }
        logger.info(f"Registered operation: {operation_key}")

    def get_tool(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get tool information.

        Args:
            name: Name of the tool

        Returns:
            Optional[Dict[str, Any]]: Tool information if found, None otherwise
        """
        return self.tools.get(name)

    def get_operation(self, tool_name: str, operation_name: str) -> Optional[Dict[str, Any]]:
        """
        Get operation information.

        Args:
            tool_name: Name of the tool
            operation_name: Name of the operation

        Returns:
            Optional[Dict[str, Any]]: Operation information if found, None otherwise
        """
        operation_key = f"{tool_name}.{operation_name}"
        return self.operations.get(operation_key)

    def execute_operation(self, tool_name: str, operation_name: str, **kwargs) -> Any:
        """
        Execute an operation on a tool.

        Args:
            tool_name: Name of the tool
            operation_name: Name of the operation
            **kwargs: Operation parameters

        Returns:
            Any: Operation result

        Raises:
            ValueError: If tool or operation not found
        """
        operation = self.get_operation(tool_name, operation_name)
        if not operation:
            raise ValueError(f"Operation not found: {tool_name}.{operation_name}")

        try:
            return operation["handler"](**kwargs)
        except Exception as e:
            logger.error(f"Error executing operation {tool_name}.{operation_name}: {str(e)}")
            raise

    def list_tools(self) -> List[str]:
        """
        List all registered tools.

        Returns:
            List[str]: List of tool names
        """
        return list(self.tools.keys())

    def list_operations(self, tool_name: Optional[str] = None) -> List[str]:
        """
        List all registered operations.

        Args:
            tool_name: Optional tool name to filter operations

        Returns:
            List[str]: List of operation names
        """
        if tool_name:
            return [op for op in self.operations.keys() if op.startswith(f"{tool_name}.")]
        return list(self.operations.keys())

    def remove_tool(self, name: str) -> bool:
        """
        Remove a tool and its operations.

        Args:
            name: Name of the tool to remove

        Returns:
            bool: True if successful, False otherwise
        """
        if name in self.tools:
            # Remove all operations for this tool
            operations_to_remove = [op for op in self.operations.keys() if op.startswith(f"{name}.")]
            for op in operations_to_remove:
                del self.operations[op]

            # Remove the tool
            del self.tools[name]
            logger.info(f"Removed tool: {name}")
            return True
        return False

    def remove_operation(self, tool_name: str, operation_name: str) -> bool:
        """
        Remove an operation.

        Args:
            tool_name: Name of the tool
            operation_name: Name of the operation

        Returns:
            bool: True if successful, False otherwise
        """
        operation_key = f"{tool_name}.{operation_name}"
        if operation_key in self.operations:
            del self.operations[operation_key]
            logger.info(f"Removed operation: {operation_key}")
            return True
        return False


def tool_operation_handler(tool_name: str, operation_name: str):
    """
    Decorator for registering tool operation handlers.

    Args:
        tool_name: Name of the tool
        operation_name: Name of the operation

    Returns:
        Callable: Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator
