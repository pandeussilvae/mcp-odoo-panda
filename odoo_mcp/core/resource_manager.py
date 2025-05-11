"""
MCP Resource Manager implementation.
This module provides centralized resource management for the MCP server.
"""

import logging
from typing import Dict, Any, List, Optional, Set, Callable
from urllib.parse import urlparse
from dataclasses import dataclass
import asyncio
from datetime import datetime, timedelta

from odoo_mcp.error_handling.exceptions import ProtocolError
from odoo_mcp.performance.caching import get_cache_manager, CACHE_TYPE

logger = logging.getLogger(__name__)

@dataclass
class Resource:
    """Resource definition."""
    uri: str
    type: str
    content: Any
    mime_type: str
    metadata: Dict[str, Any] = None
    last_modified: datetime = None
    etag: str = None

class ResourceManager:
    """
    Manages server resources and caching.
    Provides centralized access to resources and handles resource updates.
    """

    def __init__(self, cache_ttl: int = 300):
        """
        Initialize the resource manager.

        Args:
            cache_ttl: Cache time-to-live in seconds
        """
        self._cache_ttl = cache_ttl
        self._resource_handlers: Dict[str, Callable] = {}
        self._subscribers: Dict[str, Set[Callable]] = {}
        self._resource_cache: Dict[str, Resource] = {}
        self._cache_manager = get_cache_manager()

    def register_resource_handler(self, uri_pattern: str, handler: Callable) -> None:
        """
        Register a handler for a resource URI pattern.

        Args:
            uri_pattern: The URI pattern to handle
            handler: The handler function
        """
        self._resource_handlers[uri_pattern] = handler
        logger.info(f"Registered resource handler for pattern: {uri_pattern}")

    def subscribe_to_resource(self, uri: str, callback: Callable) -> None:
        """
        Subscribe to resource updates.

        Args:
            uri: The resource URI to subscribe to
            callback: The callback function to call on updates
        """
        if uri not in self._subscribers:
            self._subscribers[uri] = set()
        self._subscribers[uri].add(callback)
        logger.info(f"Subscribed to resource updates: {uri}")

    def unsubscribe_from_resource(self, uri: str, callback: Callable) -> None:
        """
        Unsubscribe from resource updates.

        Args:
            uri: The resource URI to unsubscribe from
            callback: The callback function to remove
        """
        if uri in self._subscribers:
            self._subscribers[uri].discard(callback)
            if not self._subscribers[uri]:
                del self._subscribers[uri]
            logger.info(f"Unsubscribed from resource updates: {uri}")

    async def get_resource(self, uri: str) -> Resource:
        """
        Get a resource by URI.

        Args:
            uri: The resource URI

        Returns:
            Resource: The requested resource

        Raises:
            ProtocolError: If the resource is not found or cannot be accessed
        """
        # Check cache first
        if uri in self._resource_cache:
            cached = self._resource_cache[uri]
            if cached.last_modified and datetime.now() - cached.last_modified < timedelta(seconds=self._cache_ttl):
                return cached

        # Find appropriate handler
        handler = self._find_handler(uri)
        if not handler:
            raise ProtocolError(f"No handler found for resource: {uri}")

        try:
            # Get resource from handler
            resource = await handler(uri)
            if not isinstance(resource, Resource):
                raise ProtocolError(f"Invalid resource returned by handler: {uri}")

            # Cache the resource
            self._resource_cache[uri] = resource
            return resource

        except Exception as e:
            raise ProtocolError(f"Error getting resource {uri}: {str(e)}")

    async def update_resource(self, uri: str, content: Any) -> None:
        """
        Update a resource.

        Args:
            uri: The resource URI
            content: The new content

        Raises:
            ProtocolError: If the resource cannot be updated
        """
        handler = self._find_handler(uri)
        if not handler:
            raise ProtocolError(f"No handler found for resource: {uri}")

        try:
            # Update resource through handler
            resource = await handler(uri, content)
            if not isinstance(resource, Resource):
                raise ProtocolError(f"Invalid resource returned by handler: {uri}")

            # Update cache
            self._resource_cache[uri] = resource

            # Notify subscribers
            await self._notify_subscribers(uri, resource)

        except Exception as e:
            raise ProtocolError(f"Error updating resource {uri}: {str(e)}")

    def _find_handler(self, uri: str) -> Optional[Callable]:
        """
        Find a handler for a resource URI.

        Args:
            uri: The resource URI

        Returns:
            Optional[Callable]: The handler function if found
        """
        parsed = urlparse(uri)
        for pattern, handler in self._resource_handlers.items():
            if self._match_pattern(pattern, parsed):
                return handler
        return None

    def _match_pattern(self, pattern: str, parsed: urlparse) -> bool:
        """
        Match a URI pattern against a parsed URI.

        Args:
            pattern: The URI pattern to match
            parsed: The parsed URI

        Returns:
            bool: True if the pattern matches
        """
        # Split the full URI into parts
        pattern_parts = pattern.split('/')
        uri_parts = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".split('/')
        
        if len(pattern_parts) != len(uri_parts):
            return False
            
        for pattern_part, uri_part in zip(pattern_parts, uri_parts):
            if pattern_part.startswith('{') and pattern_part.endswith('}'):
                # This is a parameter, any value is valid
                continue
            if pattern_part != uri_part:
                return False
                
        return True

    async def _notify_subscribers(self, uri: str, resource: Resource) -> None:
        """
        Notify subscribers about a resource update.

        Args:
            uri: The resource URI
            resource: The updated resource
        """
        if uri in self._subscribers:
            for callback in self._subscribers[uri]:
                try:
                    await callback(uri, resource)
                except Exception as e:
                    logger.error(f"Error notifying subscriber for {uri}: {e}")

    def clear_cache(self) -> None:
        """Clear the resource cache."""
        self._resource_cache.clear()
        logger.info("Resource cache cleared") 