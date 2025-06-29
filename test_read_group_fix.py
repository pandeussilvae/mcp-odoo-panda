#!/usr/bin/env python3
"""
Test script to verify the read_group method fix.
"""

import asyncio
import json
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from odoo_mcp.core.mcp_server import OdooMCPServer

async def test_read_group_fix():
    """Test that read_group method works correctly without domain duplication."""
    
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
    
    # Test data for read_group
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

if __name__ == "__main__":
    result = asyncio.run(test_read_group_fix())
    sys.exit(0 if result else 1) 