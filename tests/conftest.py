"""Test-wide setup: ResourceManager requires an initialized cache manager."""

import pytest

from odoo_mcp.performance.caching import initialize_cache_manager, reset_cache_manager

_MIN_CACHE_CONFIG = {"cache_ttl": 300, "cache_type": "memory", "cache_max_size": 100}


@pytest.fixture(autouse=True)
def _mcp_cache_manager_per_test():
    reset_cache_manager()
    initialize_cache_manager(_MIN_CACHE_CONFIG)
    yield
    reset_cache_manager()
