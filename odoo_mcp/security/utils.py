"""
Security utilities for Odoo MCP Server.
This module provides security-related utilities like rate limiting and data masking.
"""

import time
import asyncio
import logging
import re
from typing import Dict, Any, Optional, Union, Type, List
from collections import defaultdict

logger = logging.getLogger(__name__)  # Define logger at the top

# Import Pydantic components
try:
    from pydantic import BaseModel, ValidationError, Field, Json, field_validator

    PYDANTIC_AVAILABLE = True
    logger.info("Pydantic library found. Input validation enabled.")
except ImportError:
    logger.warning("Pydantic library not found. Input validation will be skipped.")
    logger.warning("Install pydantic for input validation: python3 -m pip install pydantic")
    PYDANTIC_AVAILABLE = False

    # Define dummy classes if Pydantic is not installed
    class BaseModel:
        pass

    class ValidationError(ValueError):
        pass

    def Field(*args, **kwargs):
        return None

    def field_validator(*args, **kwargs):
        return lambda func: func  # Dummy decorator


# --- Rate Limiting ---


class RateLimiter:
    """Rate limiter implementation."""

    def __init__(self, requests_per_minute: int = 120, max_wait_seconds: Optional[int] = None):
        """
        Initialize rate limiter.

        Args:
            requests_per_minute: Maximum number of requests per minute
            max_wait_seconds: Maximum time to wait for rate limit (None for no limit)
        """
        self.requests_per_minute = requests_per_minute
        self.max_wait_seconds = max_wait_seconds
        self.requests = defaultdict(list)
        self._cleanup_interval = 60  # Cleanup every minute

    def _cleanup_old_requests(self) -> None:
        """Remove requests older than 1 minute."""
        current_time = time.time()
        for client_id in list(self.requests.keys()):
            self.requests[client_id] = [
                req_time for req_time in self.requests[client_id] if current_time - req_time < 60
            ]
            if not self.requests[client_id]:
                del self.requests[client_id]

    def check_rate_limit(self, client_id: str) -> bool:
        """
        Check if a request is within rate limits.

        Args:
            client_id: Client identifier

        Returns:
            bool: True if within limits, False otherwise
        """
        current_time = time.time()

        # Cleanup old requests
        self._cleanup_old_requests()

        # Check rate limit
        client_requests = self.requests[client_id]
        if len(client_requests) >= self.requests_per_minute:
            oldest_request = client_requests[0]
            wait_time = 60 - (current_time - oldest_request)

            if self.max_wait_seconds is not None and wait_time > self.max_wait_seconds:
                return False

            time.sleep(wait_time)
            return True

        return True

    def record_request(self, client_id: str) -> None:
        """
        Record a request.

        Args:
            client_id: Client identifier
        """
        self.requests[client_id].append(time.time())

    def reset_limits(self) -> None:
        """Reset all rate limits."""
        self.requests.clear()


# --- Input Validation Schemas (using Pydantic) ---

if PYDANTIC_AVAILABLE:

    class BaseRequestParams(BaseModel):
        """Base Pydantic model for common request parameters."""

        session_id: Optional[str] = Field(None, description="Optional session ID for authenticated requests.")

    class EchoParams(BaseRequestParams):
        """Parameters for the 'echo' method."""

        message: str = Field("Default echo message", description="The message to echo back.")

    class CallOdooParams(BaseRequestParams):
        """Parameters for the 'call_odoo' method."""

        model: str = Field(..., description="The Odoo model name (e.g., 'res.partner').")
        odoo_method: str = Field(
            ...,
            alias="method",
            description="The method to call on the Odoo model (e.g., 'read', 'search').",
        )
        args: List[Any] = Field(default_factory=list, description="Positional arguments for the Odoo method.")
        kwargs: Dict[str, Any] = Field(default_factory=dict, description="Keyword arguments for the Odoo method.")
        service: Optional[str] = Field(
            None, description="Optional service name, primarily for JSON-RPC (e.g., 'object')."
        )

        @field_validator("model", "odoo_method")
        def _must_be_non_empty(cls, value: str) -> str:
            """Ensure model and method names are not empty."""
            if not value or not value.strip():
                raise ValueError("Field cannot be empty")
            return value.strip()

    # Generic RPC Request Model
    class RpcRequestModel(BaseModel):
        """Pydantic model representing the overall structure of a JSON-RPC request."""

        jsonrpc: str = Field("2.0", description="JSON-RPC version, must be '2.0'.")
        id: Optional[Union[str, int]] = Field(None, description="Request identifier (string or integer).")
        method: str = Field(..., description="The name of the method to be invoked.")
        # Parameters can be specific models or a generic dict as fallback
        params: Union[EchoParams, CallOdooParams, Dict[str, Any]] = Field(..., description="Parameters for the method.")

        @field_validator("jsonrpc")
        def _must_be_2_0(cls, value: str) -> str:
            """Validate jsonrpc version."""
            if value != "2.0":
                raise ValueError("jsonrpc version must be '2.0'")
            return value

        # You might need a root validator or specific logic in MCPServer
        # NOTE: Parsing params into the correct specific model (EchoParams vs CallOdooParams)
        # based on the 'method' field is handled within validate_request_data function below.

    # Mapping from method name to expected Pydantic model for params
    METHOD_PARAM_MODELS: Dict[str, Type[BaseModel]] = {
        "echo": EchoParams,
        "call_odoo": CallOdooParams,
        # Add other methods and their param models here
    }

# Define a TypedDict for the return type if not using RpcRequestModel instance
from typing import TypedDict, List, Dict, Any, Optional, Union  # Import TypedDict


class ValidatedRequestDict(TypedDict):
    jsonrpc: str
    id: Optional[Union[str, int]]
    method: str
    params: Any  # Can be a Pydantic model instance or a dict


def validate_request_data(raw_data: Dict[str, Any]) -> ValidatedRequestDict:
    """
    Validates raw request data based on JSON-RPC structure and method-specific params.

    Args:
        raw_data: The raw dictionary parsed from the incoming JSON request.

    Returns:
        A dictionary containing the validated request data. The 'params' key
        will hold either a specific Pydantic model instance (if defined and valid)
        or the original params dictionary. Returns the raw_data dict if Pydantic
        is unavailable.

    Raises:
        ValidationError: If validation fails.
        TypeError: If Pydantic is required but unavailable (alternative: return raw_data).
        ValueError: If unexpected errors occur during validation.
    """
    if not PYDANTIC_AVAILABLE:
        logger.warning("Pydantic not available, skipping input validation.")
        # Decide fallback behavior: return raw dict or raise error?
        # Returning raw dict allows operation without validation but is less safe.
        # Raising TypeError ensures validation dependency is met.
        # Let's return the raw dict for now, consistent with the check.
        # Cast to ValidatedRequestDict for type consistency, although unsafe.
        return raw_data  # type: ignore

    try:
        # --- Corrected Two-Step Validation Logic ---
        # 1. Validate base fields first, keeping params as raw dict
        class BaseRpcCheck(BaseModel):
            jsonrpc: str = Field("2.0")
            id: Optional[Union[str, int]] = None
            method: str
            params: Dict[str, Any]  # Keep as dict initially

            @field_validator("jsonrpc")
            def _must_be_2_0(cls, value: str) -> str:
                if value != "2.0":
                    raise ValueError("jsonrpc version must be '2.0'")
                return value

        # Validate the overall structure first
        base_validated = BaseRpcCheck.model_validate(raw_data)
        method_name = base_validated.method
        raw_params = base_validated.params  # Get the raw params dict

        # 2. Now, validate the raw_params using the specific model if found
        params_model = METHOD_PARAM_MODELS.get(method_name)
        final_params: Any = raw_params  # Default to raw dict if no specific model

        if params_model:
            logger.debug(f"Validating params for method '{method_name}' using {params_model.__name__}")
            # Validate the raw params dict using the specific model
            final_params = params_model.model_validate(raw_params)
        else:
            # Method doesn't have a specific params model defined
            logger.warning(f"No specific Pydantic model found for method '{method_name}' params. Params remain a dict.")

        # 3. Construct the final validated RpcRequestModel with the correctly typed params
        #    We use the original RpcRequestModel here which has the Union type for params
        final_validated_request = RpcRequestModel(
            jsonrpc=base_validated.jsonrpc,
            id=base_validated.id,
            method=method_name,
            params=final_params,  # Assign the specifically validated model or the raw dict
        )
        # Instead of returning the Pydantic model, return a dictionary
        # This avoids the Union coercion issue when params is a dict
        validated_dict: ValidatedRequestDict = {
            "jsonrpc": base_validated.jsonrpc,
            "id": base_validated.id,
            "method": method_name,
            "params": final_params,
        }

        logger.debug(f"Input validation successful for method '{method_name}'.")
        return validated_dict

    except ValidationError as e:
        logger.warning(f"Input validation failed: {e}")
        raise  # Re-raise the Pydantic validation error

    except Exception as e:
        # Catch other potential errors during validation
        logger.error(f"Unexpected error during input validation: {e}", exc_info=True)
        # Wrap in a generic ValueError or re-raise
        raise ValueError(f"Unexpected validation error: {e}") from e


# --- Old Placeholder ---
# def validate_input(data: Any, expected_schema: Dict): ... # Removed

# --- Data Masking ---

# List of common sensitive keys (customize as needed)
DEFAULT_SENSITIVE_KEYS = [
    "password",
    "api_key",
    "apikey",
    "secret",
    "token",
    "authorization",
    "auth",
    "access_key",
    "secret_key",
    "credit_card",
    "cc_number",
    "cvv",
    "ssn",
]
# Updated regex to allow optional spaces around ':' or '=' and handle various quote styles/no quotes
MASK_PATTERN = re.compile(
    r'("?(?:' + "|".join(DEFAULT_SENSITIVE_KEYS) + r')"?\s*[:=]\s*)'  # Key part (group 1)
    r"("  # Value part start (group 2)
    r'".*?"'  # Double quoted string
    r"|\'.*?\'"  # Single quoted string
    r'|[^,\s}"\']+'  # Unquoted value (up to comma, space, brace, quote)
    r")",  # Value part end
    re.IGNORECASE | re.VERBOSE,
)
MASK_REPLACEMENT = r'\1"***MASKED***"'


def mask_sensitive_data(data: Union[Dict, List, str], patterns: Optional[List[str]] = None) -> Union[Dict, List, str]:
    """
    Mask sensitive data in a data structure.

    Args:
        data: Data to mask
        patterns: List of regex patterns for sensitive keys

    Returns:
        Union[Dict, List, str]: Masked data
    """
    if patterns is None:
        patterns = [r"password", r"api_key", r"secret", r"token", r"key", r"credential"]

    if isinstance(data, dict):
        return {
            k: (
                mask_sensitive_data(v, patterns)
                if any(re.search(p, k, re.I) for p in patterns)
                else mask_sensitive_data(v, patterns)
            )
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [mask_sensitive_data(item, patterns) for item in data]
    elif isinstance(data, str):
        return "********" if any(re.search(p, data, re.I) for p in patterns) else data
    else:
        return data


# Example Usage
if __name__ == "__main__":
    # Rate Limiter Example
    async def rate_limit_test():
        limiter = RateLimiter(requests_per_minute=120, max_wait_seconds=None)  # No limit
        print("Testing rate limiter (no limit)...")
        for i in range(15):
            start_req = time.monotonic()
            print(f"Request {i+1}: Acquiring token...")
            await limiter.check_rate_limit("test_client")
            end_req = time.monotonic()
            print(f"Request {i+1}: Token acquired! (Took {end_req - start_req:.2f}s)")
            # Simulate some work
            # await asyncio.sleep(0.1)
        print("Rate limit test finished.")

    # asyncio.run(rate_limit_test())

    # Masking Example
    log_message_str = 'Processing request with headers: {"Authorization": "Bearer secret_token123", "Content-Type": "application/json"}, body: {"username": "test", "password": "mypassword!"}'
    log_data_dict = {
        "user": "admin",
        "details": {"api_key": "xyz789", "session_token": "abc123token", "other_info": "some data"},
        "credentials": ["user", "secret_pass"],
    }
    log_data_list = [1, {"secret": "my_secret"}, "normal_string"]

    print("\nTesting Masking:")
    print(f"Original String: {log_message_str}")
    print(f"Masked String:   {mask_sensitive_data(log_message_str)}")
    print(f"Original Dict: {log_data_dict}")
    print(f"Masked Dict:   {mask_sensitive_data(log_data_dict)}")
    print(f"Original List: {log_data_list}")
    print(f"Masked List:   {mask_sensitive_data(log_data_list)}")

    pass
