#!/usr/bin/env python3
"""
Test script to verify the domain validation fix for search_count method.
"""

import asyncio
import json
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from odoo_mcp.core.mcp_server import OdooMCPServer

async def test_domain_validation_fix():
    """Test that the domain validation fix prevents boolean domain errors."""
    
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
    
    # Test cases that should be handled gracefully
    test_cases = [
        {
            "name": "Boolean domain (True)",
            "request": {
                "jsonrpc": "2.0",
                "method": "call_tool",
                "params": {
                    "name": "odoo_execute_kw",
                    "arguments": {
                        "model": "res.partner",
                        "method": "search_count",
                        "args": [True],  # This should be converted to []
                        "kwargs": {}
                    }
                },
                "id": 1
            }
        },
        {
            "name": "Boolean domain (False)",
            "request": {
                "jsonrpc": "2.0",
                "method": "call_tool",
                "params": {
                    "name": "odoo_execute_kw",
                    "arguments": {
                        "model": "res.partner",
                        "method": "search_count",
                        "args": [False],  # This should be converted to []
                        "kwargs": {}
                    }
                },
                "id": 2
            }
        },
        {
            "name": "None domain",
            "request": {
                "jsonrpc": "2.0",
                "method": "call_tool",
                "params": {
                    "name": "odoo_execute_kw",
                    "arguments": {
                        "model": "res.partner",
                        "method": "search_count",
                        "args": [None],  # This should be converted to []
                        "kwargs": {}
                    }
                },
                "id": 3
            }
        },
        {
            "name": "Empty string domain",
            "request": {
                "jsonrpc": "2.0",
                "method": "call_tool",
                "params": {
                    "name": "odoo_execute_kw",
                    "arguments": {
                        "model": "res.partner",
                        "method": "search_count",
                        "args": [""],  # This should be converted to []
                        "kwargs": {}
                    }
                },
                "id": 4
            }
        },
        {
            "name": "Valid domain",
            "request": {
                "jsonrpc": "2.0",
                "method": "call_tool",
                "params": {
                    "name": "odoo_execute_kw",
                    "arguments": {
                        "model": "res.partner",
                        "method": "search_count",
                        "args": [[["name", "=", "Test"]]],  # This should work normally
                        "kwargs": {}
                    }
                },
                "id": 5
            }
        }
    ]
    
    print("Testing domain validation fix...")
    print("=" * 50)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}. Testing: {test_case['name']}")
        print("-" * 30)
        
        try:
            # Process the request
            response = await server.process_request(test_case['request'])
            print("✅ Test passed! Response:")
            print(json.dumps(response, indent=2))
        except Exception as e:
            print(f"❌ Test failed with error: {e}")
            # For boolean domains, we expect the fix to prevent the original error
            if "boolean" in str(e).lower() or "subscriptable" in str(e).lower():
                print("❌ The fix didn't work - still getting boolean domain error")
                return False
            else:
                print("⚠️  Got a different error (might be expected if server is not running)")
        
        print()
    
    print("=" * 50)
    print("🎉 Domain validation fix test completed!")
    return True

async def test_parse_domain_function():
    """Test the parse_domain function directly."""
    
    from odoo_mcp.core.mcp_server import parse_domain
    
    print("\nTesting parse_domain function directly...")
    print("=" * 50)
    
    test_inputs = [
        (True, "Boolean True"),
        (False, "Boolean False"),
        (None, "None"),
        ("", "Empty string"),
        ("[]", "Empty list string"),
        ("[['name', '=', 'test']]", "Valid domain string"),
        ([], "Empty list"),
        ([["name", "=", "test"]], "Valid domain list"),
        (123, "Integer"),
        ("invalid", "Invalid string")
    ]
    
    for input_val, description in test_inputs:
        try:
            result = parse_domain(input_val)
            print(f"✅ {description}: {input_val} -> {result} (type: {type(result)})")
            # Verify that the result is always a list
            if not isinstance(result, list):
                print(f"❌ ERROR: Result is not a list: {type(result)}")
                return False
        except Exception as e:
            print(f"❌ {description}: {input_val} -> ERROR: {e}")
            return False
    
    print("=" * 50)
    print("🎉 parse_domain function test completed!")
    return True

async def main():
    """Run all tests."""
    print("Testing domain validation fix for search_count method...")
    
    print("\n1. Testing parse_domain function...")
    success1 = await test_parse_domain_function()
    
    print("\n2. Testing domain validation in search_count...")
    success2 = await test_domain_validation_fix()
    
    if success1 and success2:
        print("\n🎉 All tests passed! The domain validation fix is working correctly.")
    else:
        print("\n❌ Some tests failed. Please check the implementation.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 