#!/usr/bin/env python3
"""
Test script to verify the read method fix.
"""

import asyncio
import json
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from odoo_mcp.core.mcp_server import OdooMCPServer

async def test_read_method_fix():
    """Test that read method works correctly without fields duplication."""
    
    # Create a minimal config for testing
    config = {
        'protocol': 'xmlrpc',
        'connection_type': 'stdio',
        'odoo': {
            'url': 'http://localhost:8069',
            'database': 'test_db',
            'username': 'test_user',
            'password': 'test_password'
        }
    }
    
    # Create server instance
    server = OdooMCPServer(config)
    
    # Test data for read method with fields in both args and kwargs
    test_request = {
        "jsonrpc": "2.0",
        "method": "call_tool",
        "params": {
            "name": "odoo_execute_kw",
            "arguments": {
                "model": "res.partner",
                "method": "read",
                "args": [
                    [1, 2, 3],  # IDs
                    ["id", "name", "email"]  # fields in args
                ],
                "kwargs": {
                    "fields": ["id", "name"],  # fields also in kwargs (should be ignored)
                    "context": {"lang": "en_US"}
                }
            }
        },
        "id": 1
    }
    
    try:
        # Process the request
        response = await server.process_request(test_request)
        print("✅ Test passed! Response:")
        print(json.dumps(response, indent=2))
        return True
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        return False

async def test_read_method_fix_call_method():
    """Test that read method works correctly in odoo_call_method tool."""
    
    # Create a minimal config for testing
    config = {
        'protocol': 'xmlrpc',
        'connection_type': 'stdio',
        'odoo': {
            'url': 'http://localhost:8069',
            'database': 'test_db',
            'username': 'test_user',
            'password': 'test_password'
        }
    }
    
    # Create server instance
    server = OdooMCPServer(config)
    
    # Test data for read method with fields in both args and kwargs
    test_request = {
        "jsonrpc": "2.0",
        "method": "call_tool",
        "params": {
            "name": "odoo_call_method",
            "arguments": {
                "model": "res.partner",
                "method": "read",
                "args": [
                    [1, 2, 3],  # IDs
                    ["id", "name", "email"]  # fields in args
                ],
                "kwargs": {
                    "fields": ["id", "name"],  # fields also in kwargs (should be ignored)
                    "context": {"lang": "en_US"}
                }
            }
        },
        "id": 1
    }
    
    try:
        # Process the request
        response = await server.process_request(test_request)
        print("✅ Test passed! Response:")
        print(json.dumps(response, indent=2))
        return True
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        return False

async def main():
    """Run all tests."""
    print("Testing read method fix...")
    
    print("\n1. Testing odoo_execute_kw tool...")
    success1 = await test_read_method_fix()
    
    print("\n2. Testing odoo_call_method tool...")
    success2 = await test_read_method_fix_call_method()
    
    if success1 and success2:
        print("\n🎉 All tests passed! The read method fix is working correctly.")
    else:
        print("\n❌ Some tests failed. Please check the implementation.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 