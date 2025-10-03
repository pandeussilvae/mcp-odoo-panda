"""
Handler Factory for Odoo Communication Protocols.
This module provides a factory pattern for creating appropriate handlers.
"""

import logging
from typing import Dict, Any, Type, Union

from odoo_mcp.core.base_handler import BaseOdooHandler
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler
from odoo_mcp.core.jsonrpc_handler import JSONRPCHandler
from odoo_mcp.error_handling.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class HandlerFactory:
    """
    Factory class for creating Odoo communication handlers.
    
    Provides a centralized way to create the appropriate handler based on
    configuration parameters.
    """
    
    _handler_registry: Dict[str, Type[BaseOdooHandler]] = {
        "xmlrpc": XMLRPCHandler,
        "jsonrpc": JSONRPCHandler,
    }
    
    @classmethod
    def create_handler(cls, protocol: str, config: Dict[str, Any]) -> BaseOdooHandler:
        """
        Create a handler instance based on the protocol type.
        
        Args:
            protocol: Protocol type ('xmlrpc' or 'jsonrpc')
            config: Configuration dictionary
            
        Returns:
            BaseOdooHandler: Appropriate handler instance
            
        Raises:
            ConfigurationError: If protocol is not supported
        """
        protocol_lower = protocol.lower()
        
        if protocol_lower not in cls._handler_registry:
            supported = ", ".join(cls._handler_registry.keys())
            raise ConfigurationError(
                f"Unsupported protocol: {protocol}. Supported protocols: {supported}"
            )
        
        handler_class = cls._handler_registry[protocol_lower]
        
        try:
            handler = handler_class(config)
            logger.info(f"Created {handler_class.__name__} for protocol: {protocol}")
            return handler
        except Exception as e:
            raise ConfigurationError(
                f"Failed to create handler for protocol {protocol}: {e}"
            )
    
    @classmethod
    def register_handler(cls, protocol: str, handler_class: Type[BaseOdooHandler]) -> None:
        """
        Register a new handler class for a protocol.
        
        Args:
            protocol: Protocol name
            handler_class: Handler class that extends BaseOdooHandler
        """
        if not issubclass(handler_class, BaseOdooHandler):
            raise ValueError(
                f"Handler class {handler_class.__name__} must extend BaseOdooHandler"
            )
        
        cls._handler_registry[protocol.lower()] = handler_class
        logger.info(f"Registered handler {handler_class.__name__} for protocol: {protocol}")
    
    @classmethod
    def get_supported_protocols(cls) -> list:
        """Get list of supported protocols."""
        return list(cls._handler_registry.keys())
    
    @classmethod
    def is_protocol_supported(cls, protocol: str) -> bool:
        """Check if a protocol is supported."""
        return protocol.lower() in cls._handler_registry


# Convenience function for backward compatibility
def create_odoo_handler(config: Dict[str, Any]) -> BaseOdooHandler:
    """
    Create an Odoo handler from configuration.
    
    Args:
        config: Configuration dictionary containing 'protocol' key
        
    Returns:
        BaseOdooHandler: Appropriate handler instance
    """
    protocol = config.get("protocol", "xmlrpc")
    return HandlerFactory.create_handler(protocol, config)
