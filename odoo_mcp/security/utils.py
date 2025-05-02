"""
Security utilities for Odoo MCP Server.
This module provides security-related utilities like rate limiting and data masking.
"""

import time
import asyncio
import logging
import re
from typing import Dict, Any, Optional, Union, Type, List

logger = logging.getLogger(__name__) # Define logger at the top

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
    class BaseModel: pass
    class ValidationError(ValueError): pass
    def Field(*args, **kwargs): return None
    def field_validator(*args, **kwargs): return lambda func: func # Dummy decorator

# --- Rate Limiting ---

class RateLimiter:
    """Rate limiter implementation."""

    def __init__(self, max_requests: int = 120, window: int = 60):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum number of requests allowed in the time window
            window: Time window in seconds
        """
        self.max_requests = max_requests
        self.window = window
        self.requests: Dict[str, List[float]] = {}

    def _cleanup_old_requests(self, key: str) -> None:
        """
        Remove requests outside the time window.

        Args:
            key: Client identifier
        """
        current_time = time.time()
        self.requests[key] = [t for t in self.requests.get(key, []) 
                            if current_time - t < self.window]

    def check_rate_limit(self, key: str) -> bool:
        """
        Check if a request is allowed under the rate limit.

        Args:
            key: Client identifier

        Returns:
            bool: True if request is allowed, False otherwise
        """
        self._cleanup_old_requests(key)
        return len(self.requests.get(key, [])) < self.max_requests

    def record_request(self, key: str) -> None:
        """
        Record a request.

        Args:
            key: Client identifier
        """
        if key not in self.requests:
            self.requests[key] = []
        self.requests[key].append(time.time())
        self._cleanup_old_requests(key)

    def get_remaining_requests(self, key: str) -> int:
        """
        Get the number of remaining requests in the current time window.

        Args:
            key: Client identifier

        Returns:
            int: Number of remaining requests
        """
        self._cleanup_old_requests(key)
        return max(0, self.max_requests - len(self.requests.get(key, [])))

    def get_reset_time(self, key: str) -> float:
        """
        Get the time until the rate limit resets.

        Args:
            key: Client identifier

        Returns:
            float: Time until reset in seconds
        """
        if not self.requests.get(key):
            return 0.0
        
        oldest_request = min(self.requests[key])
        return max(0.0, self.window - (time.time() - oldest_request))

    def reset(self, key: str) -> None:
        """
        Reset the rate limit for a key.

        Args:
            key: Client identifier
        """
        if key in self.requests:
            del self.requests[key]

    async def close(self) -> None:
        """Clean up resources."""
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
        odoo_method: str = Field(..., alias='method', description="The method to call on the Odoo model (e.g., 'read', 'search').")
        args: List[Any] = Field(default_factory=list, description="Positional arguments for the Odoo method.")
        kwargs: Dict[str, Any] = Field(default_factory=dict, description="Keyword arguments for the Odoo method.")
        service: Optional[str] = Field(None, description="Optional service name, primarily for JSON-RPC (e.g., 'object').")

        @field_validator('model', 'odoo_method')
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

        @field_validator('jsonrpc')
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
from typing import TypedDict, List, Dict, Any, Optional, Union # Import TypedDict

class ValidatedRequestDict(TypedDict):
    jsonrpc: str
    id: Optional[Union[str, int]]
    method: str
    params: Any # Can be a Pydantic model instance or a dict

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
        return raw_data # type: ignore

    try:
        # --- Corrected Two-Step Validation Logic ---
        # 1. Validate base fields first, keeping params as raw dict
        class BaseRpcCheck(BaseModel):
            jsonrpc: str = Field("2.0")
            id: Optional[Union[str, int]] = None
            method: str
            params: Dict[str, Any] # Keep as dict initially

            @field_validator('jsonrpc')
            def _must_be_2_0(cls, value: str) -> str:
                if value != "2.0": raise ValueError("jsonrpc version must be '2.0'")
                return value

        # Validate the overall structure first
        base_validated = BaseRpcCheck.model_validate(raw_data)
        method_name = base_validated.method
        raw_params = base_validated.params # Get the raw params dict

        # 2. Now, validate the raw_params using the specific model if found
        params_model = METHOD_PARAM_MODELS.get(method_name)
        final_params: Any = raw_params # Default to raw dict if no specific model

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
             params=final_params # Assign the specifically validated model or the raw dict
        )
        # Instead of returning the Pydantic model, return a dictionary
        # This avoids the Union coercion issue when params is a dict
        validated_dict: ValidatedRequestDict = {
            "jsonrpc": base_validated.jsonrpc,
            "id": base_validated.id,
            "method": method_name,
            "params": final_params
        }

        logger.debug(f"Input validation successful for method '{method_name}'.")
        return validated_dict

    except ValidationError as e:
        logger.warning(f"Input validation failed: {e}")
        raise # Re-raise the Pydantic validation error

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
    'password', 'api_key', 'apikey', 'secret', 'token',
    'authorization', 'auth', 'access_key', 'secret_key',
    'credit_card', 'cc_number', 'cvv', 'ssn'
]
# Updated regex to allow optional spaces around ':' or '=' and handle various quote styles/no quotes
MASK_PATTERN = re.compile(
    r'("?(?:' + '|'.join(DEFAULT_SENSITIVE_KEYS) + r')"?\s*[:=]\s*)' # Key part (group 1)
    r'('                                                              # Value part start (group 2)
    r'".*?"'                                                          # Double quoted string
    r'|\'.*?\''                                                       # Single quoted string
    r'|[^,\s}"\']+'                                                   # Unquoted value (up to comma, space, brace, quote)
    r')',                                                             # Value part end
    re.IGNORECASE | re.VERBOSE
)
MASK_REPLACEMENT = r'\1"***MASKED***"'

def mask_sensitive_data(data: Any, patterns: Optional[List[str]] = None) -> Any:
    """
    Mask sensitive data in the given object.

    Args:
        data: Data to mask
        patterns: List of regex patterns to match sensitive fields

    Returns:
        Any: Masked data
    """
    if patterns is None:
        patterns = [
            r'password',
            r'api_key',
            r'token',
            r'secret',
            r'credential',
            r'auth',
            r'key'
        ]

    if isinstance(data, dict):
        return {k: mask_sensitive_data(v, patterns) if any(re.search(p, k, re.I) for p in patterns)
                else mask_sensitive_data(v, patterns) for k, v in data.items()}
    elif isinstance(data, list):
        return [mask_sensitive_data(item, patterns) for item in data]
    elif isinstance(data, str) and any(re.search(p, data, re.I) for p in patterns):
        return '********'
    return data


# Example Usage
if __name__ == "__main__":
    # Rate Limiter Example
    async def rate_limit_test():
        limiter = RateLimiter(max_requests=120, window=60) # 120 requests/min
        print("Testing rate limiter (120 req/min)...")
        for i in range(15):
            start_req = time.monotonic()
            print(f"Request {i+1}: Acquiring token...")
            await limiter.acquire()
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
        "details": {
            "api_key": "xyz789",
            "session_token": "abc123token",
            "other_info": "some data"
        },
        "credentials": ["user", "secret_pass"]
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
