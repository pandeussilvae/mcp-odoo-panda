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
    """
    A simple asynchronous token bucket rate limiter.

    Allows limiting the rate of operations (e.g., requests per minute).
    Refills tokens continuously based on the specified rate.
    """
    def __init__(self, requests_per_minute: int):
        """
        Initialize the RateLimiter.

        Args:
            requests_per_minute: The maximum number of requests allowed per minute.
                                 If <= 0, rate limiting is disabled.
        """
        if requests_per_minute <= 0:
            # Rate limiting disabled or invalid config
            self.rate = float('inf')
            self.capacity = float('inf')
            self.tokens = float('inf')
            self.last_update = time.monotonic()
            self.enabled = False
            logger.info("Rate limiting disabled (requests_per_minute <= 0).")
        else:
            # Rate is tokens per second
            self.rate = requests_per_minute / 60.0
            # Capacity allows bursting up to the per-minute limit initially
            self.capacity = float(requests_per_minute)
            self.tokens = self.capacity # Start full
            self.last_update = time.monotonic()
            self.enabled = True
            self._lock = asyncio.Lock()
            logger.info(f"Rate limiter enabled: {requests_per_minute} requests/minute ({self.rate:.2f} tokens/sec)")

    async def acquire(self) -> bool:
        """
        Acquire a token from the bucket.

        If no token is available, this method waits asynchronously until one
        can be acquired.

        Returns:
            True if a token was acquired (or if rate limiting is disabled).
            False if acquiring failed after waiting (should be rare).

        Raises:
            asyncio.TimeoutError: If waiting for a token exceeds a predefined
                                  maximum wait time (TODO: implement max wait).
        """
        if not self.enabled:
            return False # Indicate disabled

        # Loop until a token can be acquired
        while True:
            # --- Start Critical Section ---
            async with self._lock:
                # Calculate time elapsed since last update
                now = time.monotonic()
                elapsed = now - self.last_update

                # Add newly generated tokens (up to capacity)
                # Important: Update tokens *before* checking availability
                current_tokens = self.tokens + elapsed * self.rate
                self.tokens = min(self.capacity, current_tokens)
                self.last_update = now # Update last_update timestamp regardless of acquisition

                logger.debug(f"Tokens updated: {self.tokens:.3f} (added {elapsed * self.rate:.3f})")

                # Check if a token is available
                if self.tokens >= 1.0:
                    # Consume a token and return success
                    self.tokens -= 1.0
                    logger.debug(f"Rate limit token acquired. Tokens remaining: {self.tokens:.3f}")
                    return True
                else:
                    # Not enough tokens, calculate required wait time
                    needed = 1.0 - self.tokens
                    # Avoid division by zero if rate is somehow zero
                    wait_time = max(0, needed / self.rate) if self.rate > 0 else float('inf')
                    # Add a small epsilon to prevent potential zero sleep and ensure yield
                    wait_time += 1e-9
                    logger.warning(f"Rate limit exceeded. Tokens: {self.tokens:.3f}. Need {needed:.3f}. Waiting for {wait_time:.4f}s")

            # --- End Critical Section (Lock Released) ---

            # Check for impossible wait (e.g., zero rate)
            if wait_time == float('inf'):
                logger.error("Rate limiter has zero rate but tokens are below 1. Cannot acquire.")
                return False # Or raise an error

            # Wait outside the lock
            try:
                # TODO: Add a maximum wait timeout using asyncio.wait_for?
                await asyncio.sleep(wait_time)
            except asyncio.CancelledError:
                logger.info("Rate limiter acquire wait cancelled.")
                raise # Propagate cancellation

            # After sleeping, the loop continues, re-acquires the lock,
            # and re-evaluates the token situation with updated elapsed time.

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

def mask_sensitive_data(data: Union[str, Dict, list, tuple, set]) -> Union[str, Dict, list, tuple, set]:
    """
    Recursively masks sensitive data in strings, dicts, lists, tuples, or sets.

    Identifies sensitive keys based on DEFAULT_SENSITIVE_KEYS and replaces their
    values with "***MASKED***". Also attempts to mask key-value pairs within
    string representations using regex.

    Args:
        data: The data structure (str, dict, list, tuple, set) to mask.

    Returns:
        A new data structure with sensitive information masked.
    """
    if isinstance(data, str):
        # Attempt to mask key-value pairs in a string format
        masked_string = MASK_PATTERN.sub(MASK_REPLACEMENT, data)
        return masked_string
    elif isinstance(data, dict):
        masked_dict = {}
        for key, value in data.items():
            # Mask based on key name
            key_str = str(key) # Ensure key is string for comparison
            if any(sensitive_key in key_str.lower() for sensitive_key in DEFAULT_SENSITIVE_KEYS):
                masked_dict[key] = "***MASKED***"
            else:
                # Recurse for nested structures
                masked_dict[key] = mask_sensitive_data(value)
        return masked_dict
    elif isinstance(data, list):
        # Recurse for items in list
        return [mask_sensitive_data(item) for item in data]
    elif isinstance(data, tuple):
         # Recurse for items in tuple, return new tuple
         return tuple(mask_sensitive_data(item) for item in data)
    elif isinstance(data, set):
         # Recurse for items in set, return new set
         return {mask_sensitive_data(item) for item in data}
    else:
        # Return other types (int, float, bool, None, etc.) unchanged
        return data


# Example Usage
if __name__ == "__main__":
    # Rate Limiter Example
    async def rate_limit_test():
        limiter = RateLimiter(requests_per_minute=10) # 10 requests/min
        print("Testing rate limiter (10 req/min)...")
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
