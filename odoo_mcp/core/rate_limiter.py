"""
Rate Limiter implementation for Odoo.
This module provides rate limiting functionality for Odoo API requests.
"""

import logging
import asyncio
import time
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from collections import deque

from odoo_mcp.error_handling.exceptions import (
    OdooMCPError,
    ConfigurationError,
    NetworkError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

# Global rate limiter instance
_rate_limiter = None


def initialize_rate_limiter(config: Dict[str, Any]) -> None:
    """
    Initialize the global rate limiter.

    Args:
        config: Configuration dictionary

    Raises:
        ConfigurationError: If the rate limiter is already initialized
    """
    global _rate_limiter
    if _rate_limiter is not None:
        raise ConfigurationError("Rate limiter is already initialized")

    requests_per_minute = config.get("requests_per_minute", 120)
    _rate_limiter = RateLimiter(requests_per_minute=requests_per_minute)
    logger.info("Rate limiter initialized successfully")


def get_rate_limiter() -> "RateLimiter":
    """
    Get the global rate limiter instance.

    Returns:
        RateLimiter: The global rate limiter instance

    Raises:
        ConfigurationError: If the rate limiter is not initialized
    """
    if _rate_limiter is None:
        raise ConfigurationError("Rate limiter is not initialized")
    return _rate_limiter


class RateLimiter:
    """
    Implements rate limiting for Odoo API requests.
    Provides request tracking, rate limiting, and error handling.
    """

    def __init__(self, requests_per_minute: int = 120):
        """
        Initialize the rate limiter.

        Args:
            requests_per_minute: Maximum number of requests allowed per minute
        """
        self.requests_per_minute = requests_per_minute
        self.window_size = 60  # 1 minute window

        # Request tracking
        self._request_times: Dict[str, deque] = {}
        self._lock = asyncio.Lock()

    async def _cleanup_old_requests(self, key: str):
        """Clean up old requests outside the time window."""
        now = time.time()
        while self._request_times[key] and now - self._request_times[key][0] > self.window_size:
            self._request_times[key].popleft()

    async def check_rate_limit(self, key: str = "default") -> bool:
        """
        Check if a request is allowed under the rate limit.

        Args:
            key: Rate limit key (e.g., user ID, IP address)

        Returns:
            bool: True if request is allowed, False otherwise
        """
        async with self._lock:
            if key not in self._request_times:
                self._request_times[key] = deque()

            # Clean up old requests
            await self._cleanup_old_requests(key)

            # Check if under rate limit
            return len(self._request_times[key]) < self.requests_per_minute

    async def record_request(self, key: str = "default"):
        """
        Record a request for rate limiting.

        Args:
            key: Rate limit key (e.g., user ID, IP address)

        Raises:
            RateLimitError: If rate limit is exceeded
        """
        async with self._lock:
            if not await self.check_rate_limit(key):
                raise RateLimitError(f"Rate limit exceeded: {self.requests_per_minute} requests per minute")

            # Record request time
            self._request_times[key].append(time.time())

    async def get_remaining_requests(self, key: str = "default") -> int:
        """
        Get the number of remaining requests in the current time window.

        Args:
            key: Rate limit key (e.g., user ID, IP address)

        Returns:
            int: Number of remaining requests
        """
        async with self._lock:
            if key not in self._request_times:
                return self.requests_per_minute

            # Clean up old requests
            await self._cleanup_old_requests(key)

            return self.requests_per_minute - len(self._request_times[key])

    async def get_reset_time(self, key: str = "default") -> float:
        """
        Get the time until the rate limit resets.

        Args:
            key: Rate limit key (e.g., user ID, IP address)

        Returns:
            float: Seconds until rate limit resets
        """
        async with self._lock:
            if key not in self._request_times or not self._request_times[key]:
                return 0.0

            # Get oldest request time
            oldest_request = self._request_times[key][0]
            reset_time = oldest_request + self.window_size - time.time()
            return max(0.0, reset_time)

    async def reset(self, key: str = "default"):
        """
        Reset the rate limit for a key.

        Args:
            key: Rate limit key (e.g., user ID, IP address)
        """
        async with self._lock:
            if key in self._request_times:
                self._request_times[key].clear()

    async def close(self):
        """Close the rate limiter and cleanup resources."""
        async with self._lock:
            self._request_times.clear()
