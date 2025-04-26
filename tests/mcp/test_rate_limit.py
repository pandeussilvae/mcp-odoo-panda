import pytest
import time
from unittest.mock import Mock
from mcp.rate_limit import RateLimiter, RateLimitError

@pytest.fixture
def mock_config():
    return Mock(
        requests_per_minute=60,
        burst_limit=10
    )

@pytest.fixture
def rate_limiter(mock_config):
    return RateLimiter(mock_config)

def test_rate_limiter_init(mock_config):
    limiter = RateLimiter(mock_config)
    assert limiter.config == mock_config
    assert limiter.requests_per_minute == 60
    assert limiter.burst_limit == 10

def test_rate_limiter_allow_request(rate_limiter):
    # Should allow requests within the rate limit
    for _ in range(10):
        assert rate_limiter.allow_request() is True

def test_rate_limiter_burst_limit(rate_limiter):
    # Should allow burst requests up to burst_limit
    for _ in range(10):
        assert rate_limiter.allow_request() is True
    
    # Should reject requests beyond burst_limit
    assert rate_limiter.allow_request() is False

def test_rate_limiter_rate_limit(rate_limiter):
    # Make requests at the rate limit
    for _ in range(60):
        assert rate_limiter.allow_request() is True
        time.sleep(1)  # Simulate 1 second between requests

def test_rate_limiter_reset(rate_limiter):
    # Make some requests
    for _ in range(5):
        rate_limiter.allow_request()
    
    # Reset the limiter
    rate_limiter.reset()
    
    # Should allow requests again
    for _ in range(10):
        assert rate_limiter.allow_request() is True

def test_rate_limiter_wait_for_slot(rate_limiter):
    # Fill up the rate limit
    for _ in range(60):
        rate_limiter.allow_request()
    
    # Should wait for a slot to become available
    start_time = time.time()
    rate_limiter.wait_for_slot()
    end_time = time.time()
    
    assert end_time - start_time >= 1  # Should wait at least 1 second

def test_rate_limiter_error_handling(rate_limiter):
    # Fill up the rate limit
    for _ in range(60):
        rate_limiter.allow_request()
    
    # Should raise RateLimitError when rate limit is exceeded
    with pytest.raises(RateLimitError):
        rate_limiter.allow_request() 