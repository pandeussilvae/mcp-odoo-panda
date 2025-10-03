#!/usr/bin/env python3
"""
Test script for refactored MCP Odoo components.
This script tests the new unified architecture and factory pattern.
"""

import asyncio
import json
import logging
import sys
from typing import Dict, Any

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration
TEST_CONFIG = {
    "odoo_url": "http://localhost:8069",
    "database": "test_db",
    "username": "test_user",
    "api_key": "test_password",
    "protocol": "xmlrpc",  # Test with XMLRPC first
    "connection_type": "stdio",
    "log_level": "INFO",
    "requests_per_minute": 60,
    "rate_limit_max_wait_seconds": 30,
    "pool_size": 5,
    "timeout": 30,
    "session_timeout_minutes": 60,
    "cache_ttl": 300,
}


async def test_handler_factory():
    """Test the handler factory pattern."""
    logger.info("Testing Handler Factory...")
    
    try:
        from odoo_mcp.core.handler_factory import HandlerFactory
        
        # Test XMLRPC handler creation
        xmlrpc_handler = HandlerFactory.create_handler("xmlrpc", TEST_CONFIG)
        logger.info(f"✓ Created XMLRPC handler: {type(xmlrpc_handler).__name__}")
        
        # Test JSONRPC handler creation
        jsonrpc_config = TEST_CONFIG.copy()
        jsonrpc_config["protocol"] = "jsonrpc"
        jsonrpc_handler = HandlerFactory.create_handler("jsonrpc", jsonrpc_config)
        logger.info(f"✓ Created JSONRPC handler: {type(jsonrpc_handler).__name__}")
        
        # Test unsupported protocol
        try:
            HandlerFactory.create_handler("unsupported", TEST_CONFIG)
            logger.error("✗ Should have raised ConfigurationError for unsupported protocol")
            return False
        except Exception as e:
            logger.info(f"✓ Correctly raised error for unsupported protocol: {type(e).__name__}")
        
        # Test protocol support check
        assert HandlerFactory.is_protocol_supported("xmlrpc")
        assert HandlerFactory.is_protocol_supported("jsonrpc")
        assert not HandlerFactory.is_protocol_supported("unsupported")
        logger.info("✓ Protocol support check working correctly")
        
        # Test supported protocols list
        protocols = HandlerFactory.get_supported_protocols()
        assert "xmlrpc" in protocols
        assert "jsonrpc" in protocols
        logger.info(f"✓ Supported protocols: {protocols}")
        
        logger.info("✓ Handler Factory tests passed!")
        return True
        
    except Exception as e:
        logger.error(f"✗ Handler Factory test failed: {e}")
        return False


async def test_base_handler():
    """Test the base handler functionality."""
    logger.info("Testing Base Handler...")
    
    try:
        from odoo_mcp.core.base_handler import BaseOdooHandler
        from odoo_mcp.core.handler_factory import HandlerFactory
        
        # Create a handler
        handler = HandlerFactory.create_handler("xmlrpc", TEST_CONFIG)
        
        # Test configuration validation
        assert handler.odoo_url == TEST_CONFIG["odoo_url"]
        assert handler.database == TEST_CONFIG["database"]
        assert handler.username == TEST_CONFIG["username"]
        assert handler.password == TEST_CONFIG["api_key"]
        logger.info("✓ Configuration validation passed")
        
        # Test hashable conversion
        test_data = {
            "list": [1, 2, 3],
            "dict": {"key": "value"},
            "string": "test",
            "int": 42
        }
        hashable = handler._make_hashable(test_data)
        logger.info(f"✓ Hashable conversion working: {type(hashable)}")
        
        # Test read method detection
        assert handler.is_read_method("object", "read")
        assert handler.is_read_method("object", "search")
        assert not handler.is_read_method("object", "write")
        assert not handler.is_read_method("common", "login")
        logger.info("✓ Read method detection working correctly")
        
        logger.info("✓ Base Handler tests passed!")
        return True
        
    except Exception as e:
        logger.error(f"✗ Base Handler test failed: {e}")
        return False


async def test_connection_pool():
    """Test the connection pool with factory."""
    logger.info("Testing Connection Pool...")
    
    try:
        from odoo_mcp.core.connection_pool import ConnectionPool
        from odoo_mcp.core.handler_factory import HandlerFactory
        
        # Create connection pool
        pool = ConnectionPool(TEST_CONFIG, HandlerFactory.create_handler)
        logger.info("✓ Connection pool created")
        
        # Test pool configuration
        assert pool.max_size == 5  # From TEST_CONFIG
        assert pool.timeout == 30
        logger.info("✓ Pool configuration correct")
        
        # Note: We can't actually test connection creation without a real Odoo instance
        # but we can test the pool structure
        assert len(pool.connections) == 0
        logger.info("✓ Pool initialized correctly")
        
        logger.info("✓ Connection Pool tests passed!")
        return True
        
    except Exception as e:
        logger.error(f"✗ Connection Pool test failed: {e}")
        return False


async def test_error_handling():
    """Test error handling and exceptions."""
    logger.info("Testing Error Handling...")
    
    try:
        from odoo_mcp.error_handling.exceptions import (
            OdooMCPError,
            AuthError,
            ConfigurationError,
            NetworkError,
            ProtocolError
        )
        
        # Test base exception
        base_error = OdooMCPError("Test error", code=-32000)
        assert base_error.message == "Test error"
        assert base_error.code == -32000
        logger.info("✓ Base exception working")
        
        # Test specific exceptions
        auth_error = AuthError("Authentication failed")
        assert auth_error.code == -32001
        logger.info("✓ AuthError working")
        
        config_error = ConfigurationError("Configuration issue")
        assert config_error.code == -32004
        logger.info("✓ ConfigurationError working")
        
        # Test JSON-RPC error conversion
        jsonrpc_error = base_error.to_jsonrpc_error()
        assert jsonrpc_error["code"] == -32000
        assert jsonrpc_error["message"] == "Test error"
        assert "exception" in jsonrpc_error["data"]
        logger.info("✓ JSON-RPC error conversion working")
        
        logger.info("✓ Error Handling tests passed!")
        return True
        
    except Exception as e:
        logger.error(f"✗ Error Handling test failed: {e}")
        return False


async def test_configuration():
    """Test configuration handling."""
    logger.info("Testing Configuration...")
    
    try:
        # Test JSON configuration parsing
        config_path = "/root/mcp-odoo-panda/mcp-odoo-panda/odoo_mcp/config/config.json"
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        # Verify required fields exist
        required_fields = ["odoo_url", "database", "username", "api_key", "protocol"]
        for field in required_fields:
            assert field in config, f"Missing required field: {field}"
        
        logger.info("✓ Configuration file is valid JSON")
        logger.info("✓ All required fields present")
        
        # Test configuration structure
        assert "http" in config
        assert "logging" in config
        logger.info("✓ Configuration structure correct")
        
        logger.info("✓ Configuration tests passed!")
        return True
        
    except Exception as e:
        logger.error(f"✗ Configuration test failed: {e}")
        return False


async def run_all_tests():
    """Run all tests and report results."""
    logger.info("=" * 60)
    logger.info("STARTING MCP ODOO REFACTORING TESTS")
    logger.info("=" * 60)
    
    tests = [
        ("Configuration", test_configuration),
        ("Handler Factory", test_handler_factory),
        ("Base Handler", test_base_handler),
        ("Connection Pool", test_connection_pool),
        ("Error Handling", test_error_handling),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        logger.info(f"\n--- Running {test_name} Tests ---")
        try:
            result = await test_func()
            results[test_name] = result
        except Exception as e:
            logger.error(f"✗ {test_name} test crashed: {e}")
            results[test_name] = False
    
    # Report results
    logger.info("\n" + "=" * 60)
    logger.info("TEST RESULTS SUMMARY")
    logger.info("=" * 60)
    
    passed = 0
    total = len(tests)
    
    for test_name, result in results.items():
        status = "PASSED" if result else "FAILED"
        logger.info(f"{test_name:20} : {status}")
        if result:
            passed += 1
    
    logger.info("=" * 60)
    logger.info(f"TOTAL: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 ALL TESTS PASSED! Refactoring successful!")
        return True
    else:
        logger.error(f"❌ {total - passed} tests failed. Check the logs above.")
        return False


if __name__ == "__main__":
    try:
        result = asyncio.run(run_all_tests())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        logger.info("\nTests interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Test runner crashed: {e}")
        sys.exit(1)
