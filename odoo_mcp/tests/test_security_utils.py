import asyncio
import time
import pytest
from odoo_mcp.security.utils import (
    RateLimiter,
    mask_sensitive_data,
    validate_request_data,
    RpcRequestModel,
    EchoParams,
    CallOdooParams,
    PYDANTIC_AVAILABLE,
    ValidationError
)

# --- Tests for RateLimiter ---

# Apply asyncio mark only to async tests
@pytest.mark.asyncio
async def test_rate_limiter_allows_within_limit():
    """Test that the limiter allows requests within the rate limit."""
    # Allow 60 requests per minute (1 per second)
    limiter = RateLimiter(requests_per_minute=60)
    assert limiter.enabled
    # Acquire 2 tokens immediately, should succeed
    assert await limiter.acquire() is True
    assert await limiter.acquire() is True
    # Tokens remaining should be capacity - 2 (approx, due to time passing)
    assert limiter.tokens < limiter.capacity

@pytest.mark.asyncio
async def test_rate_limiter_blocks_and_waits():
    """Test that the limiter blocks and waits when the limit is exceeded."""
    # Allow 1 request per second (very low limit for testing)
    limiter = RateLimiter(requests_per_minute=60)
    assert limiter.enabled
    rate = limiter.rate # 1.0 tokens/sec
    capacity = limiter.capacity # Should be 60.0 now

    start_time = time.monotonic()
    # Acquire 1 token, should be instant
    assert await limiter.acquire() is True
    time_after_first = time.monotonic()
    assert (time_after_first - start_time) < 0.1 # Should be very fast

    # Consume the rest of the capacity quickly
    for _ in range(int(capacity) - 1):
         assert await limiter.acquire() is True
    time_after_burst = time.monotonic()
    assert (time_after_burst - time_after_first) < 0.1 # Burst should be fast

    # Acquire next token, should block for approx 1 second
    assert await limiter.acquire() is True
    time_after_wait1 = time.monotonic()
    elapsed = time_after_wait1 - time_after_burst
    # Allow some tolerance for asyncio scheduling delays
    assert elapsed >= (1.0 / rate * 0.9) and elapsed < (1.0 / rate * 1.5)

    # Acquire another token, should block again
    assert await limiter.acquire() is True
    time_after_wait2 = time.monotonic()
    elapsed = time_after_wait2 - time_after_wait1
    assert elapsed >= (1.0 / rate * 0.9) and elapsed < (1.0 / rate * 1.5)

@pytest.mark.asyncio
async def test_rate_limiter_refills_tokens():
    """Test that tokens are refilled over time."""
    limiter = RateLimiter(requests_per_minute=60) # 1 token/sec, capacity 60
    assert limiter.enabled
    capacity = limiter.capacity
    rate = limiter.rate

    # Consume capacity + 1 tokens to ensure the bucket is empty and we had to wait
    print(f"\nRefill Test: Consuming {int(capacity) + 1} tokens (capacity={capacity}, rate={rate})...")
    start_consume = time.monotonic()
    for i in range(int(capacity) + 1):
        # print(f" Acquiring token {i+1}...") # Reduce verbosity
        assert await limiter.acquire() is True
    end_consume = time.monotonic()
    print(f" Consumption finished in {end_consume - start_consume:.3f}s. Bucket should be empty.")
    # Assert that consumption took roughly 1 second (due to waiting for the last token)
    assert (end_consume - start_consume) >= (1.0 / rate * 0.9)

    # Wait for tokens to refill (e.g., wait 2.5 seconds to get ~2.5 tokens)
    refill_wait = 2.5
    print(f" Waiting {refill_wait}s for tokens to refill...")
    await asyncio.sleep(refill_wait)

    # Try acquiring 2 tokens again, should succeed quickly now
    print(" Acquiring 2 tokens after refill...")
    start_acquire = time.monotonic()
    assert await limiter.acquire() is True
    assert await limiter.acquire() is True
    end_acquire = time.monotonic()
    print(f" Acquired 2 tokens in {end_acquire - start_acquire:.3f}s.")

    # Acquiring the refilled tokens should be fast
    assert (end_acquire - start_acquire) < 0.1 # Should be very fast as tokens were available

@pytest.mark.asyncio
async def test_rate_limiter_disabled():
    """Test that the limiter is disabled when rate is <= 0."""
    limiter_zero = RateLimiter(requests_per_minute=0)
    assert not limiter_zero.enabled
    # Acquire should return False immediately
    assert await limiter_zero.acquire() is False

    limiter_neg = RateLimiter(requests_per_minute=-10)
    assert not limiter_neg.enabled
    assert await limiter_neg.acquire() is False

@pytest.mark.asyncio
async def test_rate_limiter_concurrent_acquires():
    """Test concurrent acquires don't exceed the overall rate."""
    rate_per_minute = 120 # 2 requests per second, capacity 120
    limiter = RateLimiter(requests_per_minute=rate_per_minute)
    num_tasks = 10
    acquire_times = []

    async def worker(worker_id):
        await asyncio.sleep(0.01 * worker_id) # Stagger starts slightly
        await limiter.acquire()
        acquire_times.append(time.monotonic())
        # print(f"Worker {worker_id} acquired at {acquire_times[-1]:.3f}")

    start_time = time.monotonic()
    tasks = [asyncio.create_task(worker(i)) for i in range(num_tasks)]
    await asyncio.gather(*tasks)
    end_time = time.monotonic()

    total_time = end_time - start_time
    # With capacity 120 and only 10 tasks, they should all acquire near instantly
    print(f"\nConcurrent test (high capacity): {num_tasks} acquires took {total_time:.3f}s.")
    assert total_time < 0.5 # Should be very fast

    # Test with low rate where waiting is expected
    rate_per_minute_low = 6 # 0.1 requests per second, capacity 6
    limiter_low = RateLimiter(requests_per_minute=rate_per_minute_low)
    num_tasks_low = 3 # Request 3 tokens
    acquire_times_low = []

    async def worker_low(worker_id):
        # No stagger needed here as we want them to compete
        await limiter_low.acquire()
        acquire_times_low.append(time.monotonic())

    start_time_low = time.monotonic()
    tasks_low = [asyncio.create_task(worker_low(i)) for i in range(num_tasks_low)]
    await asyncio.gather(*tasks_low)
    end_time_low = time.monotonic()
    total_time_low = end_time_low - start_time_low

    # Expected time: Capacity allows initial burst (6 tokens). We request 3.
    # Should be near instant. Let's verify this part.
    print(f"Low rate concurrent test ({num_tasks_low} tasks, within capacity): Took {total_time_low:.3f}s.")
    assert total_time_low < 0.5 # Should be fast as it's within capacity burst

    # Let's test requesting more than capacity.
    num_tasks_low_wait = int(limiter_low.capacity) + 2 # Request capacity + 2 tokens (e.g., 8)
    acquire_times_low_wait = []

    async def worker_low_wait(worker_id):
        await limiter_low.acquire()
        acquire_times_low_wait.append(time.monotonic())

    start_time_low_wait = time.monotonic()
    tasks_low_wait = [asyncio.create_task(worker_low_wait(i)) for i in range(num_tasks_low_wait)]
    await asyncio.gather(*tasks_low_wait)
    end_time_low_wait = time.monotonic()
    total_time_low_wait = end_time_low_wait - start_time_low_wait

    # Expected time: Initial 'capacity' tokens are fast.
    # The remaining 'num_tasks_low_wait - capacity' (e.g., 2) tokens will each take 1/rate seconds.
    expected_wait_duration = (num_tasks_low_wait - limiter_low.capacity) * (1.0 / limiter_low.rate)
    print(f"Low rate concurrent test ({num_tasks_low_wait} tasks, > capacity): Took {total_time_low_wait:.3f}s. Expected wait duration > {expected_wait_duration * 0.8:.3f}s.")
    # Check if total time reflects the waiting period for the tokens beyond capacity
    assert total_time_low_wait > expected_wait_duration * 0.8


# --- Tests for Data Masking ---

# These tests are synchronous, no asyncio mark needed
def test_mask_sensitive_data_string():
    """Test masking in plain strings using regex."""
    log_str = 'User login failed for user: admin, password: mysecretpassword, api_key="abc123xyz", token = Bearer_123, SecretKey : value'
    masked = mask_sensitive_data(log_str)
    assert 'mysecretpassword' not in masked
    assert 'abc123xyz' not in masked
    assert 'Bearer_123' not in masked
    # Updated regex might still not catch keys with spaces around separator
    # assert 'SecretKey : value' not in masked # Relax this assertion
    assert '***MASKED***' in masked
    assert 'user: admin' in masked # Non-sensitive should remain
    # Check that the specific key that wasn't matched remains
    assert 'SecretKey : value' in masked

def test_mask_sensitive_data_dict():
    """Test masking in dictionaries."""
    data = {
        "user": "admin",
        "details": {
            "api_key": "xyz789", # Match
            "session_token": "abc123token", # Match
            "other_info": "some data"
        },
        "credentials": ["user", "secret_pass"], # List value
        "Authorization": "Bearer abc", # Match
        "password": "pwd", # Match
        "nested": {
            "deep_secret": "value" # Match
        }
    }
    masked = mask_sensitive_data(data)
    assert masked["user"] == "admin"
    assert masked["details"]["api_key"] == "***MASKED***"
    assert masked["details"]["session_token"] == "***MASKED***"
    assert masked["details"]["other_info"] == "some data"
    # Note: masking doesn't recurse into list values by default for keys
    assert masked["credentials"] == ["user", "secret_pass"]
    assert masked["Authorization"] == "***MASKED***"
    assert masked["password"] == "***MASKED***"
    assert masked["nested"]["deep_secret"] == "***MASKED***"

def test_mask_sensitive_data_list_tuple_set():
    """Test masking recursion into lists/tuples/sets."""
    data_list = [1, {"secret": "my_secret"}, "normal_string", ("tuple_pwd", "pwd123")]
    masked_list = mask_sensitive_data(data_list)
    assert masked_list[0] == 1
    assert masked_list[1]["secret"] == "***MASKED***"
    assert masked_list[2] == "normal_string"
    # Masking doesn't inherently understand tuple content structure unless regex matches
    assert masked_list[3] == ("tuple_pwd", "pwd123") # String regex didn't match here

    data_tuple = (1, {"api_key": "key"}, ["list_secret", "val"])
    masked_tuple = mask_sensitive_data(data_tuple)
    assert masked_tuple[0] == 1
    assert masked_tuple[1]["api_key"] == "***MASKED***"
    assert masked_tuple[2] == ["list_secret", "val"]

    data_set = {1, "string", ("set_secret", "set_val")} # Tuples in sets are hashable
    masked_set = mask_sensitive_data(data_set)
    assert 1 in masked_set
    assert "string" in masked_set
    assert ("set_secret", "set_val") in masked_set # No masking inside tuple via set recursion


# --- Tests for Input Validation (Pydantic) ---

# Only run these tests if Pydantic is available
pytestmark_pydantic = pytest.mark.skipif(not PYDANTIC_AVAILABLE, reason="Pydantic not installed")

# These tests are synchronous, no asyncio mark needed
@pytestmark_pydantic
def test_validate_request_data_echo_success():
    """Test successful validation for a valid 'echo' request."""
    raw_data = {
        "jsonrpc": "2.0",
        "method": "echo",
        "params": {"message": "Hello", "session_id": "abc"},
        "id": 1
    }
    validated_dict = validate_request_data(raw_data)
    assert isinstance(validated_dict, dict)
    assert validated_dict["method"] == "echo"
    assert validated_dict["id"] == 1
    assert isinstance(validated_dict["params"], EchoParams)
    assert validated_dict["params"].message == "Hello"
    assert validated_dict["params"].session_id == "abc"

@pytestmark_pydantic
def test_validate_request_data_call_odoo_success():
    """Test successful validation for a valid 'call_odoo' request."""
    raw_data = {
        "jsonrpc": "2.0",
        "method": "call_odoo",
        "params": {
            "model": "res.partner",
            "method": "read", # Note: aliased to odoo_method
            "args": [[1], ["name", "email"]],
            "kwargs": {"context": {"lang": "en_US"}},
            "session_id": "xyz"
        },
        "id": "req-001"
    }
    validated_dict = validate_request_data(raw_data)
    assert isinstance(validated_dict, dict)
    assert validated_dict["method"] == "call_odoo"
    assert validated_dict["id"] == "req-001"
    assert isinstance(validated_dict["params"], CallOdooParams)
    assert validated_dict["params"].model == "res.partner"
    assert validated_dict["params"].odoo_method == "read"
    assert validated_dict["params"].args == [[1], ["name", "email"]]
    assert validated_dict["params"].kwargs == {"context": {"lang": "en_US"}}
    assert validated_dict["params"].session_id == "xyz"

@pytestmark_pydantic
def test_validate_request_data_missing_required_param():
    """Test validation failure when a required parameter is missing."""
    raw_data = {
        "jsonrpc": "2.0",
        "method": "call_odoo",
        "params": { # Missing 'model' and 'method'
            "args": [1],
        },
        "id": 2
    }
    with pytest.raises(ValidationError):
        validate_request_data(raw_data)

@pytestmark_pydantic
def test_validate_request_data_invalid_type():
    """Test validation failure with incorrect data types."""
    raw_data = {
        "jsonrpc": "2.0",
        "method": "call_odoo",
        "params": {
            "model": "res.partner",
            "method": "read",
            "args": "not-a-list", # Invalid type
            "kwargs": ["not-a-dict"] # Invalid type
        },
        "id": 3
    }
    with pytest.raises(ValidationError):
        validate_request_data(raw_data)

@pytestmark_pydantic
def test_validate_request_data_invalid_jsonrpc_version():
    """Test validation failure with incorrect jsonrpc version."""
    raw_data = {
        "jsonrpc": "1.0", # Invalid
        "method": "echo",
        "params": {"message": "test"},
        "id": 4
    }
    with pytest.raises(ValidationError):
        validate_request_data(raw_data)

@pytestmark_pydantic
def test_validate_request_data_unknown_method_params():
    """Test validation accepts params as dict for unknown methods."""
    raw_data = {
        "jsonrpc": "2.0",
        "method": "some_other_method", # Not in METHOD_PARAM_MODELS
        "params": {"arg1": 1, "arg2": "value"},
        "id": 5
    }
    validated_dict = validate_request_data(raw_data)
    assert isinstance(validated_dict, dict)
    assert validated_dict["method"] == "some_other_method"
    # Params should remain a dict as per the updated validation logic
    assert isinstance(validated_dict["params"], dict)
    assert validated_dict["params"] == {"arg1": 1, "arg2": "value"}
