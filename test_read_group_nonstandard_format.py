#!/usr/bin/env python3
"""
Test script to verify the read_group method works with non-standard format.
"""

import asyncio
import json
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from odoo_mcp.core.mcp_server import OdooMCPServer

async def test_read_group_nonstandard_format():
    """Test that read_group method works with non-standard parameter format."""
    
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
    
    # Test data for read_group with non-standard format (all params in single object)
    test_request = {
        "jsonrpc": "2.0",
        "method": "call_tool",
        "params": {
            "name": "odoo_execute_kw",
            "arguments": {
                "model": "sale.order",
                "method": "read_group",
                "args": [
                    {
                        "groupby": ["partner_id"],
                        "kwargs": {"lazy": False},
                        "domain": [
                            ["state", "in", ["draft", "sent", "sale"]],
                            ["partner_id", "!=", 1]
                        ],
                        "fields": ["partner_id"]
                    }
                ]
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

async def test_read_group_standard_format():
    """Test that read_group method still works with standard format."""
    
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
    
    # Test data for read_group with standard format (separate parameters)
    test_request = {
        "jsonrpc": "2.0",
        "method": "call_tool",
        "params": {
            "name": "odoo_execute_kw",
            "arguments": {
                "model": "sale.order",
                "method": "read_group",
                "args": [
                    [["state", "=", "draft"]],  # domain
                    ["amount_total", "partner_id"],  # fields
                    ["partner_id"]  # groupby
                ],
                "kwargs": {
                    "limit": 10,
                    "offset": 0
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
    print("Testing read_group method with different formats...")
    
    print("\n1. Testing non-standard format (all params in single object)...")
    success1 = await test_read_group_nonstandard_format()
    
    print("\n2. Testing standard format (separate parameters)...")
    success2 = await test_read_group_standard_format()
    
    if success1 and success2:
        print("\n🎉 All tests passed! The read_group method works with both formats.")
    else:
        print("\n❌ Some tests failed. Please check the implementation.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 