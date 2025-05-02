"""
MCP Protocol Handler implementation.
This module provides centralized protocol handling for the MCP server.
"""

import json
import logging
from typing import Dict, Any, Optional, Union, Type, Literal
from pydantic import BaseModel, Field, ValidationError

from odoo_mcp.error_handling.exceptions import (
    ProtocolError, OdooMCPError, AuthError, NetworkError
)

logger = logging.getLogger(__name__)

class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 request model."""
    jsonrpc: Literal["2.0"] = "2.0"
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[Union[str, int]] = None

class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 response model."""
    jsonrpc: Literal["2.0"] = "2.0"
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    id: Optional[Union[str, int]] = None

class ProtocolHandler:
    """
    Centralized protocol handler for MCP server.
    Manages protocol version compatibility and request/response handling.
    """

    def __init__(self, protocol_version: str = "2024-01-01"):
        """
        Initialize the protocol handler.

        Args:
            protocol_version: The MCP protocol version to use
        """
        self.protocol_version = protocol_version
        self._supported_versions = {"2024-01-01"}  # Add supported versions here

    def validate_protocol_version(self, version: str) -> bool:
        """
        Validate if the protocol version is supported.

        Args:
            version: The protocol version to validate

        Returns:
            bool: True if version is supported, False otherwise
        """
        return version in self._supported_versions

    def parse_request(self, data: Union[str, Dict[str, Any]]) -> JsonRpcRequest:
        """
        Parse and validate a JSON-RPC request.

        Args:
            data: The request data (string or dict)

        Returns:
            JsonRpcRequest: The parsed and validated request

        Raises:
            ProtocolError: If the request is invalid
        """
        try:
            if isinstance(data, str):
                data = json.loads(data)
            return JsonRpcRequest(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            raise ProtocolError(f"Invalid JSON-RPC request: {str(e)}")

    def create_response(
        self,
        request_id: Optional[Union[str, int]],
        result: Optional[Any] = None,
        error: Optional[Dict[str, Any]] = None
    ) -> JsonRpcResponse:
        """
        Create a JSON-RPC response.

        Args:
            request_id: The request ID to include in the response
            result: The result to include (if no error)
            error: The error to include (if any)

        Returns:
            JsonRpcResponse: The formatted response
        """
        return JsonRpcResponse(
            result=result,
            error=error,
            id=request_id
        )

    def create_error_response(
        self,
        request_id: Optional[Union[str, int]],
        code: int,
        message: str,
        data: Optional[Any] = None
    ) -> JsonRpcResponse:
        """
        Create a JSON-RPC error response.

        Args:
            request_id: The request ID to include in the response
            code: The error code
            message: The error message
            data: Optional additional error data

        Returns:
            JsonRpcResponse: The formatted error response
        """
        error = {
            "code": code,
            "message": message
        }
        if data is not None:
            error["data"] = data

        return self.create_response(request_id=request_id, error=error)

    def handle_protocol_error(self, error: Exception) -> JsonRpcResponse:
        """
        Handle protocol-related errors and convert them to JSON-RPC responses.

        Args:
            error: The exception to handle

        Returns:
            JsonRpcResponse: The formatted error response
        """
        if isinstance(error, ProtocolError):
            return self.create_error_response(
                request_id=None,
                code=-32602,
                message=str(error)
            )
        elif isinstance(error, AuthError):
            return self.create_error_response(
                request_id=None,
                code=-32001,
                message=str(error)
            )
        elif isinstance(error, NetworkError):
            return self.create_error_response(
                request_id=None,
                code=-32002,
                message=str(error)
            )
        else:
            return self.create_error_response(
                request_id=None,
                code=-32603,
                message=f"Internal error: {str(error)}"
            ) 