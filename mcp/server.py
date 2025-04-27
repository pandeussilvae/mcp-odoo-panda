"""
MCP (Model Context Protocol) server base class.
This module provides the base implementation for MCP servers.
"""

import asyncio
import json
import logging
import sys
from typing import Dict, Any, List, Optional, Union, Callable
from abc import ABC, abstractmethod

from mcp.resource_types import (
    Resource,
    ResourceType,
    Tool,
    Prompt,
    Server,
    ServerInfo,
    ClientInfo,
    ResourceTemplate,
    GetPromptResult,
    PromptMessage
)
from mcp.config import load_config
from mcp.client import MCPClient
from mcp.log_config import setup_logging

logger = logging.getLogger(__name__)

class MCPServer(Server):
    """
    Base class for MCP servers.
    Provides the core functionality and interface for MCP protocol implementation.
    """

    def __init__(self, name: str, version: str):
        """
        Initialize the MCP server.

        Args:
            name: The name of the server
            version: The version of the server
        """
        self.name = name
        self.version = version
        self._running = False
        self._shutdown_requested = False

    @property
    @abstractmethod
    def capabilities(self) -> Dict[str, Any]:
        """
        Get the server's capabilities.
        Must be implemented by subclasses.
        """
        pass

    @abstractmethod
    async def initialize(self, client_info: ClientInfo) -> ServerInfo:
        """
        Initialize the server with client information.
        Must be implemented by subclasses.

        Args:
            client_info: Information about the client

        Returns:
            ServerInfo object with server capabilities
        """
        pass

    @abstractmethod
    async def get_resource(self, uri: str) -> Resource:
        """
        Get a resource by URI.
        Must be implemented by subclasses.

        Args:
            uri: The URI of the resource to get

        Returns:
            The requested resource
        """
        pass

    @abstractmethod
    async def list_resources(self, template: Optional[ResourceTemplate] = None) -> List[Resource]:
        """
        List available resources.
        Must be implemented by subclasses.

        Args:
            template: Optional template to filter resources

        Returns:
            List of matching resources
        """
        pass

    @abstractmethod
    async def list_tools(self) -> List[Tool]:
        """
        List available tools.
        Must be implemented by subclasses.

        Returns:
            List of available tools
        """
        pass

    @abstractmethod
    async def list_prompts(self) -> List[Prompt]:
        """
        List available prompts.
        Must be implemented by subclasses.

        Returns:
            List of available prompts
        """
        pass

    @abstractmethod
    async def get_prompt(self, name: str, args: Dict[str, Any]) -> GetPromptResult:
        """
        Get a prompt by name.
        Must be implemented by subclasses.

        Args:
            name: The name of the prompt
            args: Arguments for the prompt

        Returns:
            The prompt result
        """
        pass

    async def run(self):
        """
        Run the server.
        This method should be implemented by subclasses to handle the specific
        protocol implementation (stdio, SSE, etc.).
        """
        self._running = True
        try:
            while not self._shutdown_requested:
                await asyncio.sleep(1)
        finally:
            self._running = False

    async def stop(self):
        """
        Stop the server gracefully.
        """
        self._shutdown_requested = True
        while self._running:
            await asyncio.sleep(0.1)

async def main():
    """
    Main entry point for the MCP server.
    """
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='MCP Server')
    parser.add_argument('--config', required=True, help='Path to configuration file')
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Set up logging
    setup_logging(config.logging)
    
    # Create server instance
    server = MCPServer(name="MCP Server", version="1.0.0")
    
    try:
        # Run the server
        await server.run()
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        await server.stop()
    except Exception as e:
        logger.error(f"Server error: {e}")
        await server.stop()
        raise

if __name__ == '__main__':
    asyncio.run(main()) 