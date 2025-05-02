"""
Resource Manager implementation for Odoo MCP Server.
This module provides resource management and operation handling functionality.
"""

import logging
from typing import Dict, Any, Optional, List, Callable, Union
from functools import wraps

logger = logging.getLogger(__name__)

class ResourceManager:
    """Manages Odoo resources and their operations."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the resource manager.

        Args:
            config: Configuration dictionary containing resource settings
        """
        self.config = config
        self.resources: Dict[str, Dict[str, Any]] = {}
        self.operations: Dict[str, Dict[str, Any]] = {}
        self._register_default_resources()

    def _register_default_resources(self) -> None:
        """Register default Odoo resources."""
        self.register_resource(
            name="res.partner",
            description="Odoo Partner/Contact resource",
            operations=["create", "read", "update", "delete", "search"]
        )
        
        self.register_resource(
            name="res.users",
            description="Odoo User resource",
            operations=["create", "read", "update", "delete", "search"]
        )
        
        self.register_resource(
            name="res.company",
            description="Odoo Company resource",
            operations=["read", "update"]
        )

    def register_resource(self, name: str, description: str, operations: List[str]) -> None:
        """
        Register a new resource.

        Args:
            name: Name of the resource
            description: Description of the resource
            operations: List of supported operations
        """
        self.resources[name] = {
            'description': description,
            'operations': operations
        }
        logger.info(f"Registered resource: {name}")

    def register_operation(self, resource_name: str, operation_name: str, handler: Callable) -> None:
        """
        Register an operation handler for a resource.

        Args:
            resource_name: Name of the resource
            operation_name: Name of the operation
            handler: Operation handler function
        """
        if resource_name not in self.resources:
            raise ValueError(f"Resource not found: {resource_name}")
        
        if operation_name not in self.resources[resource_name]['operations']:
            raise ValueError(f"Operation not supported for resource {resource_name}: {operation_name}")
        
        operation_key = f"{resource_name}.{operation_name}"
        self.operations[operation_key] = {
            'handler': handler,
            'resource': resource_name,
            'operation': operation_name
        }
        logger.info(f"Registered operation: {operation_key}")

    def get_resource(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get resource information.

        Args:
            name: Name of the resource

        Returns:
            Optional[Dict[str, Any]]: Resource information if found, None otherwise
        """
        return self.resources.get(name)

    def get_operation(self, resource_name: str, operation_name: str) -> Optional[Dict[str, Any]]:
        """
        Get operation information.

        Args:
            resource_name: Name of the resource
            operation_name: Name of the operation

        Returns:
            Optional[Dict[str, Any]]: Operation information if found, None otherwise
        """
        operation_key = f"{resource_name}.{operation_name}"
        return self.operations.get(operation_key)

    def execute_operation(self, resource_name: str, operation_name: str, **kwargs) -> Any:
        """
        Execute an operation on a resource.

        Args:
            resource_name: Name of the resource
            operation_name: Name of the operation
            **kwargs: Operation parameters

        Returns:
            Any: Operation result

        Raises:
            ValueError: If resource or operation not found
        """
        operation = self.get_operation(resource_name, operation_name)
        if not operation:
            raise ValueError(f"Operation not found: {resource_name}.{operation_name}")
        
        try:
            return operation['handler'](**kwargs)
        except Exception as e:
            logger.error(f"Error executing operation {resource_name}.{operation_name}: {str(e)}")
            raise

    def list_resources(self) -> List[str]:
        """
        List all registered resources.

        Returns:
            List[str]: List of resource names
        """
        return list(self.resources.keys())

    def list_operations(self, resource_name: Optional[str] = None) -> List[str]:
        """
        List all registered operations.

        Args:
            resource_name: Optional resource name to filter operations

        Returns:
            List[str]: List of operation names
        """
        if resource_name:
            return [op for op in self.operations.keys() if op.startswith(f"{resource_name}.")]
        return list(self.operations.keys())

    def remove_resource(self, name: str) -> bool:
        """
        Remove a resource and its operations.

        Args:
            name: Name of the resource to remove

        Returns:
            bool: True if successful, False otherwise
        """
        if name in self.resources:
            # Remove all operations for this resource
            operations_to_remove = [op for op in self.operations.keys() if op.startswith(f"{name}.")]
            for op in operations_to_remove:
                del self.operations[op]
            
            # Remove the resource
            del self.resources[name]
            logger.info(f"Removed resource: {name}")
            return True
        return False

    def remove_operation(self, resource_name: str, operation_name: str) -> bool:
        """
        Remove an operation.

        Args:
            resource_name: Name of the resource
            operation_name: Name of the operation

        Returns:
            bool: True if successful, False otherwise
        """
        operation_key = f"{resource_name}.{operation_name}"
        if operation_key in self.operations:
            del self.operations[operation_key]
            logger.info(f"Removed operation: {operation_key}")
            return True
        return False

def operation_handler(resource_name: str, operation_name: str):
    """
    Decorator for registering operation handlers.

    Args:
        resource_name: Name of the resource
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

# Global resource manager instance
resource_manager: Optional[ResourceManager] = None

def initialize_resource_manager(config: Dict[str, Any]) -> None:
    """
    Initialize the global resource manager.

    Args:
        config: Configuration dictionary
    """
    global resource_manager
    resource_manager = ResourceManager(config)
    logger.info("Resource manager initialized") 