"""
MCP (Model Context Protocol) stdio protocol implementation.
This module provides the stdio-based communication protocol for MCP.
"""

import asyncio
import json
import logging
import sys
from typing import Dict, Any, Optional, Callable
from enum import Enum

logger = logging.getLogger(__name__)

class EnumEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        return super().default(obj)

class StdioProtocol:
    """
    Implements the MCP protocol over stdio.
    Handles JSON-RPC communication over stdin/stdout.
    """

    def __init__(self, request_handler: Callable[[Dict[str, Any]], Dict[str, Any]]):
        """
        Initialize the stdio protocol handler.

        Args:
            request_handler: Callback function to handle incoming requests
        """
        self.request_handler = request_handler
        self._running = False

    async def run(self):
        """
        Run the stdio protocol handler.
        Reads JSON-RPC requests from stdin and writes responses to stdout.
        """
        self._running = True
        try:
            while self._running:
                # Read a line from stdin
                line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                if not line:
                    break

                try:
                    # Parse the JSON-RPC request
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError("Request must be a JSON object")

                    # Handle the request
                    response = self.request_handler(request)

                    # Write the response to stdout
                    print(json.dumps(response, cls=EnumEncoder), flush=True)

                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON in request: {e}")
                    error_response = {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32700,
                            "message": "Parse error"
                        },
                        "id": None
                    }
                    print(json.dumps(error_response, cls=EnumEncoder), flush=True)

                except Exception as e:
                    logger.error(f"Error handling request: {e}")
                    error_response = {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32603,
                            "message": "Internal error"
                        },
                        "id": None
                    }
                    print(json.dumps(error_response, cls=EnumEncoder), flush=True)

        finally:
            self._running = False

    def stop(self):
        """
        Stop the stdio protocol handler.
        """
        self._running = False 