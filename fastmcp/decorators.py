"""
FastMCP decorators module.
This module provides decorators for FastMCP handlers.
"""

import functools
import logging
from typing import Callable, Any, Optional, Dict, TypeVar, cast

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=Callable[..., Any])

def mcp_handler(func: T) -> T:
    """
    Decorator for MCP handlers.
    
    Args:
        func: Function to decorate
        
    Returns:
        Decorated function
    """
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in MCP handler: {str(e)}")
            raise
    return cast(T, wrapper)

def mcp_resource(func: T) -> T:
    """
    Decorator for MCP resource handlers.
    
    Args:
        func: Function to decorate
        
    Returns:
        Decorated function
    """
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in MCP resource handler: {str(e)}")
            raise
    return cast(T, wrapper)

def mcp_tool(func: T) -> T:
    """
    Decorator for MCP tool handlers.
    
    Args:
        func: Function to decorate
        
    Returns:
        Decorated function
    """
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in MCP tool handler: {str(e)}")
            raise
    return cast(T, wrapper) 